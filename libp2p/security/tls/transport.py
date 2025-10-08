from dataclasses import dataclass
import ssl
from typing import Any

from cryptography import x509

from libp2p.abc import IRawConnection, ISecureConn, ISecureTransport
from libp2p.crypto.keys import KeyPair, PrivateKey
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID
from libp2p.security.secure_session import SecureSession
from libp2p.security.tls.certificate import (
    ALPN_PROTOCOL,
    create_cert_template,
    generate_certificate,
    verify_certificate_chain,
)
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
        # Generate and cache a stable identity certificate for this transport
        template = (
            self._identity_config.cert_template
            if self._identity_config and self._identity_config.cert_template
            else create_cert_template()
        )
        self._cert_pem, self._key_pem = generate_certificate(
            self.libp2p_privkey, template
        )
        # Trusted peer certs (PEM) for accepting self-signed peers during tests
        self._trusted_peer_certs_pem: list[str] = []

    def create_ssl_context(self, server_side: bool = False) -> ssl.SSLContext:
        """
        Create SSL context for TLS connections.

        Args:
            server_side: Whether this is for server-side connections

        Returns:
            Configured SSL context

        Raises:
            ValueError: If any trusted certificate contains dangerous content

        """
        # Validate trusted peer certificates for security vulnerabilities
        for cert_pem in self._trusted_peer_certs_pem:
            # Check for path traversal attempts and dangerous characters
            dangerous_patterns = ["..", "\x00", "&", "|", ";", "$"]
            if any(pattern in cert_pem for pattern in dangerous_patterns):
                raise ValueError(
                    "Certificate contains dangerous characters "
                    "Or path traversal attempt"
                )

            # Check for reasonable certificate size
            if len(cert_pem) > 10000:  # 10KB max for a reasonable cert
                raise ValueError("Certificate exceeds maximum allowed size")

            # Check for very long lines that could indicate path injection
            if any(len(line) > 1000 for line in cert_pem.split("\n")):
                raise ValueError("Certificate contains suspiciously long lines")

        # Placeholder for SSL context creation following libp2p TLS 1.3 profile.
        # Expected responsibilities:
        # - TLS 1.3 only
        # - Insecure cert verification here, custom verification post-handshake
        # - Set ALPN protocols: preferred muxers + "libp2p"
        # - Apply key log writer if provided in identity_config
        # - Disable SNI for client-side connections
        ctx = ssl.SSLContext(
            ssl.PROTOCOL_TLS_SERVER if server_side else ssl.PROTOCOL_TLS_CLIENT
        )
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        # We do our own verification of the peer certificate
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_OPTIONAL if server_side else ssl.CERT_NONE

        # Load our cached self-signed certificate bound to libp2p identity
        import os
        import tempfile

        # On Windows, we need to close the file before SSL can access it
        # Use delete=False and manual cleanup for cross-platform compatibility
        cert_file = tempfile.NamedTemporaryFile("w", delete=False)
        key_file = tempfile.NamedTemporaryFile("w", delete=False)

        cert_path = cert_file.name
        key_path = key_file.name

        try:
            cert_file.write(self._cert_pem)
            cert_file.flush()
            cert_file.close()

            key_file.write(self._key_pem)
            key_file.flush()
            key_file.close()

            # Now load the certificates - files are closed so Windows can access them
            ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        finally:
            # Manual cleanup - remove temp files
            try:
                if os.path.exists(cert_path):
                    os.unlink(cert_path)
            except (OSError, PermissionError):
                pass  # Best effort cleanup
            try:
                if os.path.exists(key_path):
                    os.unlink(key_path)
            except (OSError, PermissionError):
                pass  # Best effort cleanup

        # If we have trusted peer certs, configure verification to accept those
        if server_side and self._trusted_peer_certs_pem:
            ca_file = tempfile.NamedTemporaryFile("w", delete=False)
            ca_path = ca_file.name
            try:
                ca_file.write("".join(self._trusted_peer_certs_pem))
                ca_file.flush()
                ca_file.close()
                ctx.load_verify_locations(cafile=ca_path)
                ctx.verify_mode = ssl.CERT_OPTIONAL
            except Exception:
                pass
            finally:
                # Manual cleanup
                try:
                    if os.path.exists(ca_path):
                        os.unlink(ca_path)
                except (OSError, PermissionError):
                    pass  # Best effort cleanup

        # ALPN: provide list; without a select-callback we accept server preference.
        alpn_list = list(self._preferred_muxers) + [ALPN_PROTOCOL]
        try:
            ctx.set_alpn_protocols(alpn_list)
        except Exception:
            # ALPN may be unavailable; proceed without early muxer negotiation
            pass

        # key log file support if provided as path-like
        if self._identity_config and self._identity_config.key_log_writer:
            # Accept a file path or a file-like with name
            keylog_path = None
            writer = self._identity_config.key_log_writer
            if isinstance(writer, str):
                keylog_path = writer
            elif hasattr(writer, "name"):
                keylog_path = getattr(writer, "name")
            if keylog_path:
                try:
                    ctx.keylog_filename = keylog_path
                except Exception:
                    pass

        return ctx

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
            raise ValueError("missing peer certificate")

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
            raise ValueError("missing peer certificate")

        # Extract and verify remote public key
        remote_public_key = self._extract_public_key_from_cert(peer_cert)
        remote_peer_id = ID.from_pubkey(remote_public_key)

        if remote_peer_id != peer_id:
            raise ValueError(
                f"Peer ID mismatch: expected {peer_id} got {remote_peer_id}"
            )

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
        # Use our chain verifier to extract the host public key
        return verify_certificate_chain([cert])

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
        # Negotiated muxer is available from the TLSReadWriter after handshake.
        # It's surfaced on the SecureSession via connection state in other impls.
        # For now, not exposed at this layer.
        return None

    # Expose local certificate for tests
    def get_certificate_pem(self) -> str:
        return self._cert_pem

    def trust_peer_cert_pem(self, pem: str) -> None:
        """
        Add a trusted peer certificate PEM.

        Args:
            pem: The PEM-encoded certificate to trust

        Raises:
            ValueError: If the certificate contains invalid characters or format

        """
        # Security validation
        if not pem:
            raise ValueError("Empty certificate PEM")

        # Check for path traversal attempts and dangerous characters
        dangerous_patterns = ["..", "\x00", "&", "|", ";", "$"]
        if any(pattern in pem for pattern in dangerous_patterns):
            raise ValueError(
                "Certificate PEM contains dangerous characters "
                "or path traversal attempt"
            )

        # Check for reasonable PEM size
        if len(pem) > 10000:  # 10KB max for a reasonable cert
            raise ValueError("Certificate PEM exceeds maximum allowed size")

        # Basic PEM format validation for legitimate certificates
        if not pem.strip().startswith("-----BEGIN"):
            raise ValueError("Invalid PEM format - must start with BEGIN marker")

        self._trusted_peer_certs_pem.append(pem)


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
