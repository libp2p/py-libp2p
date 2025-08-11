from dataclasses import dataclass
import ssl
from typing import Any

from cryptography import x509

from libp2p.abc import IRawConnection, ISecureConn, ISecureTransport
from libp2p.crypto.keys import KeyPair, PrivateKey
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID
from libp2p.security.secure_session import SecureSession
from libp2p.security.tls.io import TLSReadWriter

# Protocol ID for TLS transport
PROTOCOL_ID = TProtocol("/tls/1.0.0")


@dataclass
class IdentityConfig:
    """Configuration for TLS identity."""

    cert_template: x509.CertificateBuilder | None = None
    key_log_writer: Any | None = None


class TLSTransport(ISecureTransport):
    """
    TLS transport implementation following the noise pattern.

    Features:
    - TLS 1.3 support
    - Custom certificate generation with libp2p extensions
    - Peer ID verification
    - ALPN protocol negotiation
    """

    libp2p_privkey: PrivateKey
    local_peer: ID
    early_data: bytes | None

    def __init__(
        self,
        libp2p_keypair: KeyPair,
        early_data: bytes | None = None,
        muxers: list[str] | None = None,
        identity_config: IdentityConfig | None = None,
    ):
        """Initialize TLS transport."""
        self.libp2p_privkey = libp2p_keypair.private_key
        self.local_peer = ID.from_pubkey(libp2p_keypair.public_key)
        self.early_data = early_data
        # Optional list of preferred stream muxers for ALPN negotiation.
        self._preferred_muxers = muxers or []
        # Optional identity config for certificate template and key log writer.
        self._identity_config = identity_config

    def create_ssl_context(self, server_side: bool = False) -> ssl.SSLContext:
        """
        Create SSL context for TLS connections.

        Args:
            server_side: Whether this is for server-side connections

        Returns:
            Configured SSL context

        """
        # Placeholder for SSL context creation following libp2p TLS 1.3 profile.
        # Expected responsibilities:
        # - TLS 1.3 only
        # - Insecure cert verification here, custom verification post-handshake
        # - Set ALPN protocols: preferred muxers + "libp2p"
        # - Apply key log writer if provided in identity_config
        # - Disable SNI for client-side connections
        raise NotImplementedError("SSL context creation not implemented")

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Secure an inbound connection as server.

        Args:
            conn: Raw connection to secure

        Returns:
            Secured connection (SecureSession)

        """
        # Create SSL context for server
        ssl_context = self.create_ssl_context(server_side=True)

        # Create TLS reader/writer
        tls_reader_writer = TLSReadWriter(
            conn=conn, ssl_context=ssl_context, server_side=True
        )

        # Perform handshake
        await tls_reader_writer.handshake()

        # Extract peer information
        peer_cert = tls_reader_writer.get_peer_certificate()
        if not peer_cert:
            raise NotImplementedError("Peer certificate extraction not implemented")

        # Extract remote public key from certificate
        remote_public_key = self._extract_public_key_from_cert(peer_cert)
        remote_peer_id = ID.from_pubkey(remote_public_key)

        # Return SecureSession like noise does
        return SecureSession(
            local_peer=self.local_peer,
            local_private_key=self.libp2p_privkey,
            remote_peer=remote_peer_id,
            remote_permanent_pubkey=remote_public_key,
            is_initiator=False,
            conn=tls_reader_writer,
        )

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """
        Secure an outbound connection as client.

        Args:
            conn: Raw connection to secure
            peer_id: Expected peer ID

        Returns:
            Secured connection (SecureSession)

        """
        # Create SSL context for client
        ssl_context = self.create_ssl_context(server_side=False)

        # Create TLS reader/writer
        tls_reader_writer = TLSReadWriter(
            conn=conn, ssl_context=ssl_context, server_side=False
        )

        # Perform handshake
        await tls_reader_writer.handshake()

        # Extract peer information
        peer_cert = tls_reader_writer.get_peer_certificate()
        if not peer_cert:
            raise NotImplementedError("Peer certificate extraction not implemented")

        # Extract and verify remote public key
        remote_public_key = self._extract_public_key_from_cert(peer_cert)
        remote_peer_id = ID.from_pubkey(remote_public_key)

        if remote_peer_id != peer_id:
            raise NotImplementedError("Peer ID verification not implemented")

        # Return SecureSession like noise does
        return SecureSession(
            local_peer=self.local_peer,
            local_private_key=self.libp2p_privkey,
            remote_peer=peer_id,
            remote_permanent_pubkey=remote_public_key,
            is_initiator=True,
            conn=tls_reader_writer,
        )

    def _extract_public_key_from_cert(self, cert: x509.Certificate) -> Any:
        """Extract public key from certificate."""
        raise NotImplementedError(
            "Public key extraction from certificate not implemented"
        )

    def get_protocol_id(self) -> TProtocol:
        """Get the protocol ID for this transport."""
        return PROTOCOL_ID

    def get_preferred_muxers(self) -> list[str]:
        """
        Return the list of preferred stream muxers for ALPN negotiation.
        """
        return list(self._preferred_muxers)

    def get_negotiated_muxer(self) -> str | None:
        """
        Placeholder: return the muxer negotiated via ALPN, if any.
        """
        raise NotImplementedError("Negotiated muxer retrieval not implemented")


# Factory function for creating TLS transport
def create_tls_transport(
    libp2p_keypair: KeyPair,
    early_data: bytes | None = None,
    muxers: list[str] | None = None,
    identity_config: IdentityConfig | None = None,
) -> TLSTransport:
    """
    Create a new TLS transport.

    Args:
        libp2p_keypair: Key pair for the local peer
        early_data: Optional early data for TLS handshake
        muxers: Optional list of preferred stream muxer protocol IDs for ALPN
        identity_config: Optional TLS identity config (cert template, key log writer)

    Returns:
        TLS transport instance

    """
    return TLSTransport(libp2p_keypair, early_data, muxers, identity_config)
