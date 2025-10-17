"""
TLS I/O utilities for libp2p.

This module provides TLS-specific message reading and writing functionality,
similar to how noise handles encrypted communication.
"""

import ssl

from cryptography import x509
import trio

from libp2p.abc import IRawConnection
from libp2p.io.abc import EncryptedMsgReadWriter


class TLSReadWriter(EncryptedMsgReadWriter):
    """
    TLS encrypted message reader/writer.

    This class handles TLS encryption/decryption over a raw connection,
    similar to NoiseTransportReadWriter in the noise implementation.
    """

    def __init__(
        self,
        conn: IRawConnection,
        ssl_context: ssl.SSLContext,
        server_side: bool = False,
        server_hostname: str | None = None,
    ):
        """
        Initialize TLS reader/writer.

        Args:
            conn: Raw connection to wrap
            ssl_context: SSL context for TLS operations
            server_side: Whether to act as TLS server
            server_hostname: Server hostname for client connections

        """
        self.raw_connection = conn
        self.ssl_context = ssl_context
        self.server_side = server_side
        self.server_hostname = server_hostname
        # These will be initialized in handshake() and required for operation
        self._ssl_socket: ssl.SSLObject
        self._in_bio: ssl.MemoryBIO
        self._out_bio: ssl.MemoryBIO
        self._peer_certificate: x509.Certificate | None = None
        self._handshake_complete = False
        self._negotiated_protocol: str | None = None
        # Track whether the TLS wrapper has been closed to prevent I/O after close
        self._closed = False

    async def handshake(self) -> None:
        """
        Perform TLS handshake.

        Raises:
            HandshakeFailure: If handshake fails due to protocol errors
            RuntimeError: If handshake timeout or connection errors occur
            ssl.SSLError: For SSL-specific errors not related to want read/write

        Notes:
            - Implements defense against slow handshakes that could tie up resources
            - Properly handles connection errors and cleanup
            - Verifies minimum TLS version (1.3)

        """
        # Perform a blocking-style TLS handshake using memory BIOs bridged to
        # Trio stream
        in_bio = ssl.MemoryBIO()
        out_bio = ssl.MemoryBIO()
        ssl_obj = self.ssl_context.wrap_bio(
            in_bio,
            out_bio,
            server_side=self.server_side,
            server_hostname=self.server_hostname,
        )
        self._ssl_socket = ssl_obj
        self._in_bio = in_bio
        self._out_bio = out_bio

        # Drive the handshake with timeout
        MAX_HANDSHAKE_TIME = 30  # 30 seconds max for handshake
        handshake_attempts = 0
        MAX_ATTEMPTS = 100  # Prevent infinite loops

        with trio.move_on_after(MAX_HANDSHAKE_TIME):
            while handshake_attempts < MAX_ATTEMPTS:
                handshake_attempts += 1
                try:
                    ssl_obj.do_handshake()
                    # Verify TLS version after handshake
                    version = ssl_obj.version()
                    if version is None or not version.startswith("TLSv1.3"):
                        raise RuntimeError(f"Unsupported TLS version: {version}")
                    break
                except ssl.SSLWantReadError:
                    # flush data to wire
                    data = out_bio.read()
                    if data:
                        await self.raw_connection.write(data)
                    # read more from wire with timeout
                    try:
                        with trio.move_on_after(5):  # 5 second read timeout
                            incoming = await self.raw_connection.read(4096)
                            if incoming:
                                in_bio.write(incoming)
                            elif incoming == b"":  # Connection closed
                                raise RuntimeError("Connection closed during handshake")
                    except trio.TooSlowError:
                        raise RuntimeError("Handshake read timeout")
                except ssl.SSLWantWriteError:
                    data = out_bio.read()
                    if data:
                        try:
                            with trio.move_on_after(5):  # 5 second write timeout
                                await self.raw_connection.write(data)
                        except trio.TooSlowError:
                            raise RuntimeError("Handshake write timeout")
                except ssl.SSLCertVerificationError:
                    # Ignore built-in verification errors;
                    # we verify manually afterwards.
                    break
                except ssl.SSLError as e:
                    raise RuntimeError(f"SSL error during handshake: {e}")
            else:
                raise RuntimeError("Too many handshake attempts")

        # Flush any remaining handshake data
        data = out_bio.read()
        if data:
            await self.raw_connection.write(data)

        # Populate cert and ALPN
        # For our usage we skip builtin verification, so peer cert may be self-signed.
        # Use binary form if available; otherwise use text form unsupported.
        try:
            cert_bin = ssl_obj.getpeercert(binary_form=True)
        except TypeError:
            cert_bin = None
        if cert_bin:
            self._peer_certificate = x509.load_der_x509_certificate(cert_bin)
        self._negotiated_protocol = ssl_obj.selected_alpn_protocol()
        self._handshake_complete = True

    def get_peer_certificate(self) -> x509.Certificate | None:
        """
        Get the peer's certificate after handshake.

        Returns:
            Peer certificate or None if not available

        """
        return self._peer_certificate

    async def write_msg(self, msg: bytes) -> None:
        """
        Write an encrypted message.

        Args:
            msg: Message to encrypt and send

        """
        # Ensure handshake was called and connection is open
        if self._closed:
            raise RuntimeError("Cannot write: TLS connection is closed")
        if not self._handshake_complete:
            raise RuntimeError("Call handshake() first")
        # write plaintext into SSL object and flush ciphertext to transport
        remaining = msg
        while remaining:
            try:
                n = self._ssl_socket.write(remaining)
                remaining = remaining[n:]
            except ssl.SSLWantWriteError:
                pass
            # flush any TLS records produced
            while True:
                data = self._out_bio.read()
                if not data:
                    break
                await self.raw_connection.write(data)

    async def read_msg(self) -> bytes:
        """
        Read and decrypt a message.

        Returns:
            Decrypted message bytes

        """
        # Ensure handshake was called and connection is open
        if self._closed:
            raise RuntimeError("Cannot read: TLS connection is closed")
        if not self._handshake_complete:
            raise RuntimeError("Call handshake() first")

        # Try to read decrypted application data; if need more TLS bytes,
        # fetch from network
        max_attempts = 100  # Prevent infinite loops
        attempt = 0

        while attempt < max_attempts:
            attempt += 1
            try:
                data = self._ssl_socket.read(65536)
                if data:
                    return data
                # If we get here, ssl_socket.read() returned empty data
                # Check if connection is closed by trying to read from raw connection
                try:
                    incoming = await self.raw_connection.read(4096)
                    if not incoming:
                        return b""  # Connection closed
                    self._in_bio.write(incoming)
                    continue  # Try reading again with new data
                except Exception:
                    return b""  # Connection error
            except ssl.SSLWantReadError:
                # flush any pending TLS data
                pending = self._out_bio.read()
                if pending:
                    await self.raw_connection.write(pending)
                # get more ciphertext
                incoming = await self.raw_connection.read(4096)
                if not incoming:
                    return b""
                self._in_bio.write(incoming)
                continue
            except Exception:
                # Any other SSL error - connection is likely broken
                return b""

        # If we've exhausted attempts, return empty
        return b""

    def encrypt(self, data: bytes) -> bytes:
        """
        Encrypt data for transmission.

        Args:
            data: Data to encrypt

        Returns:
            Encrypted data

        """
        # In TLS, encryption is handled at the SSL layer during write_msg
        # This method exists for interface compatibility
        return data

    def decrypt(self, data: bytes) -> bytes:
        """
        Decrypt received data.

        Args:
            data: Encrypted data to decrypt

        Returns:
            Decrypted data

        """
        # In TLS, decryption is handled at the SSL layer during read_msg
        # This method exists for interface compatibility
        return data

    async def close(self) -> None:
        """Close the TLS connection."""
        try:
            if self._ssl_socket is not None:
                try:
                    self._ssl_socket.unwrap()
                except Exception:
                    pass
        finally:
            await self.raw_connection.close()
            # Mark as closed so subsequent reads/writes raise
            self._closed = True

    def get_negotiated_protocol(self) -> str | None:
        """
        Return the ALPN-negotiated protocol (e.g., selected muxer) if any.
        """
        return self._negotiated_protocol

    def get_remote_address(self) -> tuple[str, int] | None:
        """
        Get remote address from underlying connection.

        Returns:
            Remote address tuple or None

        """
        if hasattr(self.raw_connection, "get_remote_address"):
            return self.raw_connection.get_remote_address()
        return None
