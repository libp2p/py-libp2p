from dataclasses import dataclass
import logging
import ssl
from typing import Any

from cryptography import x509
from cryptography.x509.oid import ExtensionOID

import libp2p
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
import libp2p.utils
import libp2p.utils.paths

logger = logging.getLogger("libp2p.security.tls")

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
        enable_autotls: bool = False,
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
        self.enable_autotls = enable_autotls

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
        logger.debug("TLS create_ssl_context: starting (server_side=%s)", server_side)
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
        logger.debug("TLS create_ssl_context: creating SSL context")

        ctx = ssl.SSLContext(
            ssl.PROTOCOL_TLS_SERVER if server_side else ssl.PROTOCOL_TLS_CLIENT
        )
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        # We do our own verification (like Go's InsecureSkipVerify).
        # Python's ssl module can't request a client cert without CA verification.
        # TODO: Implement proper mutual TLS with custom verification
        ctx.check_hostname = False

        # TODO: Fix this default: no client cert verification
        # INBOUND connection can't ask for tls cert from remote peers
        # ctx.verify_mode = ssl.CERT_OPTIONAL if server_side else ssl.CERT_NONE
        ctx.verify_mode = ssl.CERT_NONE

        # Load our cached self-signed certificate bound to libp2p identity
        import os
        import tempfile

        # On Windows, we need to close the file before SSL can access it
        # Use delete=False and manual cleanup for cross-platform compatibility
        cert_file = tempfile.NamedTemporaryFile("w", delete=False)
        key_file = tempfile.NamedTemporaryFile("w", delete=False)

        cert_path = cert_file.name
        key_path = key_file.name

        logger.debug("TLS create_ssl_context: writing cert/key to temp files")

        try:
            cert_file.write(self._cert_pem)
            cert_file.flush()
            cert_file.close()

            key_file.write(self._key_pem)
            key_file.flush()
            key_file.close()

            # Now load the certificates - files are closed so Windows can access them
            # Fetch the auto-tls certificate if already cached
            # TODO: remove this temp-bool
            if self.enable_autotls:
                if libp2p.utils.paths.AUTOTLS_CERT_PATH.exists():
                    pem_bytes = libp2p.utils.paths.AUTOTLS_CERT_PATH.read_bytes()
                    cert_chain = x509.load_pem_x509_certificates(pem_bytes)

                    san = (
                        cert_chain[0]
                        .extensions.get_extension_for_oid(
                            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
                        )
                        .value
                    )
                    dns_names = san.get_values_for_type(x509.DNSName)  # type: ignore
                    # Load both certificate and private key
                    if libp2p.utils.paths.AUTOTLS_KEY_PATH.exists():
                        ctx.load_cert_chain(
                            certfile=libp2p.utils.paths.AUTOTLS_CERT_PATH,
                            keyfile=libp2p.utils.paths.AUTOTLS_KEY_PATH,
                        )
                        logger.info(
                            "[INC/OUT]: Loaded existing cert, DNS: %s", dns_names
                        )
                    else:
                        logger.warning(
                            "[INC/OUT]: AutoTLS certificate found but private"
                            "key missing. Falling back to self-signed certificate."
                        )
                        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)

                else:
                    logger.info(
                        "[INC/OUT]: AUTO-TLS enabled, but ACME certificate"
                        "not cached yet, so reverting back to self-signed TLS"
                    )

                    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
            else:
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

        logger.debug("TLS create_ssl_context: loading certificate chain")

        # Load trusted peer certs as CA certificates if present
        # This enables mutual TLS when peers explicitly trust each other's certs
        if self._trusted_peer_certs_pem and server_side:
            print("loading trust store")
            for i, cert_pem in enumerate(self._trusted_peer_certs_pem):
                ca_file = tempfile.NamedTemporaryFile("w", delete=False, suffix=".pem")
                ca_path = ca_file.name
                try:
                    ca_file.write(cert_pem)
                    ca_file.flush()
                    ca_file.close()
                    ctx.load_verify_locations(cafile=ca_path)
                finally:
                    try:
                        if os.path.exists(ca_path):
                            os.unlink(ca_path)
                    except (OSError, PermissionError):
                        pass
            # Request client cert and verify against trusted CAs
            ctx.verify_mode = ssl.CERT_OPTIONAL
            cnt = len(self._trusted_peer_certs_pem)
            logger.debug("TLS: loaded %d trusted certs", cnt)

        # ALPN: Set up protocol list with preferred muxers + "libp2p" fallback
        # Note: Python's ssl module doesn't support set_alpn_select_callback
        # like Go does, so we can't prefer client's choice on server side.
        # The server will prefer its own order. To maximize compatibility,
        # we put the "libp2p" fallback last so muxers are tried first.
        alpn_list = list(self._preferred_muxers) + [ALPN_PROTOCOL]
        try:
            ctx.set_alpn_protocols(alpn_list)
            logger.debug("TLS create_ssl_context: ALPN protocols set: %s", alpn_list)
        except Exception as e:
            # ALPN may be unavailable; proceed without early muxer negotiation
            logger.debug("TLS create_ssl_context: ALPN not available: %s", e)

        logger.debug("TLS create_ssl_context: configuring ALPN and key log")

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
        logger.debug("TLS create_ssl_context: completed")

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
        local_prim_pk = self.libp2p_privkey.get_public_key().serialize()
        tls_reader_writer = TLSReadWriter(
            conn=conn,
            ssl_context=ssl_context,
            local_prim_pk=local_prim_pk,
            server_side=True,
        )

        # Perform handshake
        logger.debug("TLS secure_inbound: starting handshake")
        await tls_reader_writer.handshake(enable_autotls=self.enable_autotls)
        logger.debug("TLS secure_inbound: handshake completed successfully")

        # Extract peer information
        peer_cert = tls_reader_writer.get_peer_certificate()
        if not peer_cert:
            logger.warning("[INBOUND] Server couldn't fetch dialer's certificate")

            # TODO: Python ssl can't request client cert without CA verification.
            # Use placeholder peer ID - client can still verify server identity.
            logger.warning("TLS inbound: no peer cert (Python ssl limitation)")

            # Extaract the keys from primitive key-exchange, if autotls enabled
            if self.enable_autotls:
                remote_public_key = tls_reader_writer.remote_primitive_pk
                remote_peer_id = tls_reader_writer.remote_primitive_peerid
                logger.warning(
                    "TLS inbound: using peerid obtained from primitive key-exchange"
                )
            else:
                placeholder_keypair = libp2p.generate_new_ed25519_identity()
                remote_public_key = placeholder_keypair.public_key
                remote_peer_id = ID.from_pubkey(remote_public_key)
                logger.error(
                    "TLS inbound: using peerid obtained from placeholder keypair"
                )

            # This is the case when the autotls is enabled, and we did a self-signed
            # certificate handshake with AUTO-TLS BROKER, and naturally we didn't do the
            # primitive peer-identify exchange, so again use a placeholde
            if self.enable_autotls and remote_peer_id is None:
                placeholder_keypair = libp2p.generate_new_ed25519_identity()
                remote_public_key = placeholder_keypair.public_key
                remote_peer_id = ID.from_pubkey(remote_public_key)

            if remote_peer_id is None:
                raise ValueError(
                    "remote peer ID must be known before creating SecureSession"
                )

            if remote_public_key is None:
                raise ValueError(
                    "remote public-key must be known before creating SecureSession"
                )

            session = SecureSession(
                local_peer=self.local_peer,
                local_private_key=self.libp2p_privkey,
                remote_peer=remote_peer_id,
                remote_permanent_pubkey=remote_public_key,
                is_initiator=False,
                conn=tls_reader_writer,
            )
            logger.debug("TLS secure_inbound: returning placeholder SecureSession")
            return session

        # Extract remote public key from certificate
        logger.debug("TLS secure_inbound: extracting public key from certificate")
        remote_public_key = self._extract_public_key_from_cert(peer_cert)
        remote_peer_id = ID.from_pubkey(remote_public_key)
        logger.debug("TLS secure_inbound: extracted peer ID %s", remote_peer_id)
        logger.debug("TLS secure_inbound: creating SecureSession")
        # Return SecureSession like noise does
        session = SecureSession(
            local_peer=self.local_peer,
            local_private_key=self.libp2p_privkey,
            remote_peer=remote_peer_id,
            remote_permanent_pubkey=remote_public_key,
            is_initiator=False,
            conn=tls_reader_writer,
        )
        logger.debug("TLS secure_inbound: SecureSession created, returning")
        return session

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
        local_prim_pk = self.libp2p_privkey.get_public_key().serialize()
        tls_reader_writer = TLSReadWriter(
            conn=conn,
            ssl_context=ssl_context,
            local_prim_pk=local_prim_pk,
            server_side=False,
        )

        # Perform handshake
        logger.debug("TLS outbound: handshake starting (peer=%s)", peer_id)
        await tls_reader_writer.handshake(enable_autotls=self.enable_autotls)
        logger.debug("TLS secure_outbound: handshake completed successfully")

        # Extract peer information and domain from the peer-cert
        peer_cert = tls_reader_writer.get_peer_certificate()
        dns_names = None

        # # TODO: These will be used in certificate verification
        # local_cert_pubkey_pem = None
        # cert_signature = None

        if self.enable_autotls and peer_cert is not None:
            # Extract DNS names
            san = peer_cert.extensions.get_extension_for_oid(
                ExtensionOID.SUBJECT_ALTERNATIVE_NAME
            ).value
            dns_names = san.get_values_for_type(x509.DNSName)  # type: ignore

            # # Pubkey and signature will be used in certificate verification
            # # Extract public key
            # pubkey = peer_cert.public_key()
            # local_cert_pubkey_pem = pubkey.public_bytes(
            #     encoding=serialization.Encoding.PEM,
            #     format=serialization.PublicFormat.SubjectPublicKeyInfo,
            # ).decode()

            # # Extract signature from the certificate
            # cert_signature = peer_cert.signature.hex()

            logger.info("[OUTBOUND] Remote peer-cert: DNS: %s", dns_names)

        if not peer_cert:
            raise ValueError("missing peer certificate")

        # Try to extract peer ID from certificate
        # Autotls certificates may not have the libp2p extension
        try:
            remote_public_key = self._extract_public_key_from_cert(peer_cert)
            remote_peer_id = ID.from_pubkey(remote_public_key)

            if remote_peer_id != peer_id:
                logger.error(
                    "TLS: peer mismatch want=%s got=%s", peer_id, remote_peer_id
                )
                raise ValueError(
                    f"Peer ID mismatch: expected {peer_id} got {remote_peer_id}"
                )

            logger.debug(
                "TLS outbound: peer verified from certificate, connection established"
            )

        except ValueError as e:
            if "expected certificate to contain the key extension" in str(e):
                # Autotls certificate without libp2p extension
                # Skip certificate-based peer verification - rely on identify protocol
                logger.warning(
                    "[TLS outbound]: certificate missing libp2p extension "
                    "(likely autotls cert)."
                )

                logger.warning("Skipping certificate-based peer verification. ")

                # Extract remote identify from primitive exchange
                # and verify it against expected peer-id
                prim_remote_public_key = tls_reader_writer.remote_primitive_pk
                prim_remote_peer_id = tls_reader_writer.remote_primitive_peerid

                if prim_remote_peer_id != peer_id:
                    logger.error(
                        "Primitive and expected peer-id mismatch."
                        "Dropping the connection"
                    )
                    raise

                remote_peer_id = prim_remote_peer_id
                remote_public_key = prim_remote_public_key

                logger.warning(
                    "[TLS outbound]: using public key, from primitive exchange. "
                )
            else:
                raise

        if remote_public_key is None:
            raise ValueError(
                "remote_public_key must be set before creating SecureSession"
            )

        logger.debug("[TLS outbound]: connection established")

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
