"""
TLS I/O utilities for libp2p.

This module provides TLS-specific stream reading and writing functionality.
Unlike Noise (which is message-based), TLS is a stream protocol, so we use
it directly as a stream without additional message framing.
"""

import logging
import ssl

from cryptography import x509
import trio

from libp2p.abc import IRawConnection
from libp2p.io.abc import EncryptedMsgReadWriter, ReadWriteCloser

logger = logging.getLogger(__name__)


class TLSStreamReadWriter(ReadWriteCloser):
    """
    Low-level TLS stream reader/writer that handles SSL socket operations.

    This class provides the raw TLS encryption/decryption as a stream.
    Used by TLSReadWriter which adapts it to EncryptedMsgReadWriter.
    """

    def __init__(
        self,
        conn: IRawConnection,
        ssl_context: ssl.SSLContext,
        server_side: bool = False,
        server_hostname: str | None = None,
    ):
        self.raw_connection = conn
        self.ssl_context = ssl_context
        self.server_side = server_side
        self.server_hostname = server_hostname
        self._ssl_socket: ssl.SSLObject
        self._in_bio: ssl.MemoryBIO
        self._out_bio: ssl.MemoryBIO
        self._peer_certificate: x509.Certificate | None = None
        self._handshake_complete = False
        self._negotiated_protocol: str | None = None
        self._closed = False
        # Read buffer for bytes that arrive during/after handshake
        self._read_buffer = bytearray()

    async def handshake(self) -> None:
        """Perform TLS handshake."""
        logger.debug("TLS handshake starting (server_side=%s)", self.server_side)
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

        MAX_HANDSHAKE_TIME = 30
        handshake_attempts = 0
        MAX_ATTEMPTS = 100

        with trio.move_on_after(MAX_HANDSHAKE_TIME):
            while handshake_attempts < MAX_ATTEMPTS:
                handshake_attempts += 1
                logger.debug(
                    "TLS handshake attempt %d/%d", handshake_attempts, MAX_ATTEMPTS
                )  # noqa: E501
                try:
                    ssl_obj.do_handshake()
                    version = ssl_obj.version()
                    if version is None or not version.startswith("TLSv1.3"):
                        raise RuntimeError(f"Unsupported TLS version: {version}")
                    logger.debug("TLS handshake done (version=%s)", version)
                    break
                except ssl.SSLWantReadError:
                    data = out_bio.read()
                    if data:
                        logger.debug("TLS handshake: flushing %d bytes", len(data))
                        await self.raw_connection.write(data)
                    try:
                        with trio.move_on_after(5):
                            incoming = await self.raw_connection.read(4096)
                            if incoming:
                                logger.debug("TLS: read %d bytes", len(incoming))
                                in_bio.write(incoming)
                            elif incoming == b"":
                                raise RuntimeError("Connection closed during handshake")
                    except trio.TooSlowError:
                        raise RuntimeError("Handshake read timeout")
                except ssl.SSLWantWriteError:
                    data = out_bio.read()
                    if data:
                        logger.debug("TLS handshake: write flush %d bytes", len(data))
                        try:
                            with trio.move_on_after(5):
                                await self.raw_connection.write(data)
                        except trio.TooSlowError:
                            raise RuntimeError("Handshake write timeout")
                except ssl.SSLCertVerificationError:
                    logger.debug("TLS handshake: ignoring cert verify error")
                    break
                except ssl.SSLError as e:
                    logger.error("TLS handshake: SSL error: %s", e)
                    raise RuntimeError(f"SSL error during handshake: {e}")
            else:
                logger.error("TLS handshake: too many attempts (%d)", MAX_ATTEMPTS)
                raise RuntimeError("Too many handshake attempts")

        # Flush any remaining output from handshake (e.g., NewSessionTicket in TLS 1.3)
        data = out_bio.read()
        if data:
            logger.debug("TLS handshake: flushing %d remaining bytes", len(data))
            await self.raw_connection.write(data)

        # Post-handshake TLS messages (e.g. NewSessionTicket) are processed
        # later when read() is called. Don't read application data here.
        pending_in = in_bio.pending
        if pending_in > 0:
            logger.debug("TLS handshake: %d bytes pending in buffer", pending_in)
        else:
            logger.debug("TLS handshake: input buffer is clean after handshake")

        try:
            cert_bin = ssl_obj.getpeercert(binary_form=True)
        except TypeError:
            cert_bin = None
        if cert_bin:
            self._peer_certificate = x509.load_der_x509_certificate(cert_bin)
            print(self._peer_certificate)
            logger.debug("TLS handshake: loaded peer certificate")
        raw_protocol = ssl_obj.selected_alpn_protocol()
        # Handle "libp2p" ALPN fallback: means no early muxer negotiation
        if raw_protocol == "libp2p":
            self._negotiated_protocol = None
            logger.debug("TLS: ALPN 'libp2p' (no early muxer)")
        else:
            self._negotiated_protocol = raw_protocol
            if self._negotiated_protocol:
                logger.debug("TLS: ALPN muxer: %s", self._negotiated_protocol)
        self._handshake_complete = True
        logger.debug("TLS handshake: handshake complete flag set")

    async def write(self, data: bytes) -> None:
        """Write raw bytes to TLS stream."""
        if self._closed:
            raise RuntimeError("Cannot write: TLS connection is closed")
        if not self._handshake_complete:
            raise RuntimeError("Call handshake() first")

        logger.debug("TLS write: writing %d bytes to SSL socket", len(data))
        remaining = data
        bytes_written = 0
        while remaining:
            try:
                n = self._ssl_socket.write(remaining)
                remaining = remaining[n:]
                bytes_written += n
                logger.debug("TLS write: %d bytes (%d left)", n, len(remaining))
            except ssl.SSLWantWriteError:
                # Need to flush output before continuing
                pass
            # Flush all encrypted output
            while True:
                out_data = self._out_bio.read()
                if not out_data:
                    break
                await self.raw_connection.write(out_data)
                logger.debug("TLS write: flushed %d bytes", len(out_data))

        # Ensure all encrypted data is flushed
        while True:
            out_data = self._out_bio.read()
            if not out_data:
                break
            await self.raw_connection.write(out_data)
            logger.debug("TLS write: flushed %d more bytes", len(out_data))

        logger.debug("TLS write: completed - %d plaintext bytes written", bytes_written)

    async def read(self, n: int | None = None) -> bytes:
        """Read raw bytes from TLS stream."""
        if self._closed:
            raise RuntimeError("Cannot read: TLS connection is closed")
        if not self._handshake_complete:
            raise RuntimeError("Call handshake() first")

        if n is None:
            n = 65536

        # First, drain from read buffer if available
        if self._read_buffer:
            if len(self._read_buffer) <= n:
                # Return all buffered data
                result = bytes(self._read_buffer)
                self._read_buffer.clear()
                logger.debug("TLS read: returning %d bytes from buffer", len(result))
                return result
            else:
                # Return requested amount, keep rest in buffer
                result = bytes(self._read_buffer[:n])
                self._read_buffer = self._read_buffer[n:]
                logger.debug("TLS read: %d bytes from buffer", len(result))
                return result

        # No buffered data, read from SSL socket
        # TLS is a stream protocol. Return data as soon as available.
        # Important for protocols that send small messages.
        max_attempts = 100
        attempt = 0
        buffer = bytearray()

        while attempt < max_attempts:
            attempt += 1

            # Flush any pending output first (TLS might need to send something)
            pending_output = self._out_bio.read()
            if pending_output:
                await self.raw_connection.write(pending_output)
                logger.debug("TLS read: flushed %d output bytes", len(pending_output))

            # If _in_bio is empty, read from raw connection first
            if self._in_bio.pending == 0:
                try:
                    incoming = await self.raw_connection.read(4096)
                    if incoming:
                        self._in_bio.write(incoming)
                        logger.debug("TLS read: %d encrypted bytes", len(incoming))
                    elif incoming == b"":
                        # Connection closed
                        if buffer:
                            logger.debug("TLS read: conn closed, %d bytes", len(buffer))
                            break
                        logger.debug("TLS read: connection closed (no data)")
                        break
                except Exception as e:
                    logger.debug("TLS read: error reading from raw connection: %s", e)
                    break

            # Try to read from SSL socket
            try:
                data = self._ssl_socket.read(min(n if n else 65536, 65536))
                if data:
                    buffer.extend(data)
                    logger.debug("TLS read: %d decrypted bytes", len(data))
                    # Return immediately when we have data (stream semantics)
                    break
                else:
                    # SSL socket returned empty - might need more data
                    # Continue to read more from raw connection
                    continue
            except ssl.SSLWantReadError:
                # SSL socket needs more encrypted data
                # This is normal - continue loop to read more from raw connection
                logger.debug("TLS read: SSLWantReadError attempt=%d", attempt)
                continue
            except ssl.SSLError as e:
                # SSL errors can occur for various reasons
                error_str = str(e)
                logger.debug("TLS read: SSL error: %s", e)

                # TLS alerts from peer are usually fatal
                if "alert" in error_str.lower():
                    logger.warning("TLS read: TLS alert from peer: %s", e)
                    break

                # EOF errors indicate connection closed
                if "EOF" in error_str:
                    logger.debug("TLS read: EOF error, connection closed")
                    break

                # For other SSL errors, if we have data, return it
                if buffer:
                    break
                # Otherwise re-raise
                raise
            except Exception as e:
                logger.debug("TLS read: unexpected error: %s", e)
                break

        result = bytes(buffer)
        if result:
            logger.debug("TLS read: returning %d bytes", len(result))
        elif not result and attempt >= max_attempts:
            logger.warning("TLS read: max attempts reached (%d)", max_attempts)
        return result

    def get_peer_certificate(self) -> x509.Certificate | None:
        return self._peer_certificate

    def get_negotiated_protocol(self) -> str | None:
        return self._negotiated_protocol

    def get_remote_address(self) -> tuple[str, int] | None:
        if hasattr(self.raw_connection, "get_remote_address"):
            return self.raw_connection.get_remote_address()
        return None

    async def close(self) -> None:
        logger.debug("TLS close: closing connection")
        try:
            if hasattr(self, "_ssl_socket") and self._ssl_socket is not None:
                try:
                    self._ssl_socket.unwrap()
                    logger.debug("TLS close: SSL socket unwrapped")
                except Exception as e:
                    logger.debug("TLS close: exception during SSL unwrap: %s", e)
        finally:
            await self.raw_connection.close()
            self._closed = True
            logger.debug("TLS close: connection closed")


class TLSReadWriter(EncryptedMsgReadWriter):
    """
    TLS encrypted stream reader/writer.

    This class handles TLS encryption/decryption over a raw connection.
    Unlike Noise (which is message-based), TLS is a stream protocol.
    We use it directly as a stream, allowing multistream's varint framing
    to work over the TLS stream (like Go's implementation).

    The pattern matches Go's TLS implementation:
    1. Write plaintext directly to TLS stream (no additional framing)
    2. Read chunks from TLS stream (multistream handles varint parsing)
    """

    stream_writer: TLSStreamReadWriter

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
        # Create the underlying TLS stream handler
        self.stream_writer = TLSStreamReadWriter(
            conn, ssl_context, server_side, server_hostname
        )

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
        await self.stream_writer.handshake()

    def get_peer_certificate(self) -> x509.Certificate | None:
        """
        Get the peer's certificate after handshake.

        Returns:
            Peer certificate or None if not available

        """
        return self.stream_writer.get_peer_certificate()

    async def write_msg(self, msg: bytes) -> None:
        """
        Write data to TLS stream (no additional framing).

        Data is encrypted by TLS and sent over the raw connection.
        """
        logger.debug("TLS write_msg: writing %d bytes to stream", len(msg))
        await self.stream_writer.write(msg)
        logger.debug("TLS write_msg: done (plaintext=%d)", len(msg))

    async def read_msg(self) -> bytes:
        """
        Read data from TLS stream (no message framing).

        Returns a chunk of decrypted data from the TLS stream.
        """
        logger.debug("TLS read_msg: reading from stream")
        # Read a chunk from the TLS stream
        # SecureSession will buffer and multistream will parse varint messages
        data = await self.stream_writer.read(65536)  # Read up to 64KB
        if not data:
            logger.debug("TLS read_msg: connection closed (no data)")
            return b""  # Connection closed
        logger.debug("TLS read_msg: read %d bytes from stream", len(data))
        return data

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
        logger.debug("TLS close: closing connection")
        await self.stream_writer.close()
        logger.debug("TLS close: connection closed")

    def get_negotiated_protocol(self) -> str | None:
        """
        Return the ALPN-negotiated protocol (e.g., selected muxer) if any.
        """
        return self.stream_writer.get_negotiated_protocol()

    def get_remote_address(self) -> tuple[str, int] | None:
        """
        Get remote address from underlying connection.

        Returns:
            Remote address tuple or None

        """
        return self.stream_writer.get_remote_address()
