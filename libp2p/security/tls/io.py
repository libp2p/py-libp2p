"""
TLS I/O utilities for libp2p.

This module provides TLS-specific message reading and writing functionality,
similar to how noise handles encrypted communication.
"""

import ssl

from cryptography import x509

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
        self._ssl_socket = None
        self._peer_certificate: x509.Certificate | None = None
        self._handshake_complete = False

    async def handshake(self) -> None:
        """
        Perform TLS handshake.

        Raises:
            HandshakeFailure: If handshake fails

        """
        raise NotImplementedError("TLS handshake not implemented")

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
        raise NotImplementedError("TLS write_msg not implemented")

    async def read_msg(self) -> bytes:
        """
        Read and decrypt a message.

        Returns:
            Decrypted message bytes

        """
        raise NotImplementedError("TLS read_msg not implemented")

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
        raise NotImplementedError("TLS close not implemented")

    def get_remote_address(self) -> tuple[str, int] | None:
        """
        Get remote address from underlying connection.

        Returns:
            Remote address tuple or None

        """
        if hasattr(self.raw_connection, "get_remote_address"):
            return self.raw_connection.get_remote_address()
        return None
