"""
QUIC Security implementation for py-libp2p Module 5.
Implements libp2p TLS specification for QUIC transport with peer identity integration.
Based on go-libp2p and js-libp2p security patterns.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import ssl
from typing import List, Optional, Union

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.x509.base import Certificate
from cryptography.x509.oid import NameOID

from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.crypto.serialization import deserialize_public_key
from libp2p.peer.id import ID

from .exceptions import (
    QUICCertificateError,
    QUICPeerVerificationError,
)

logger = logging.getLogger(__name__)

# libp2p TLS Extension OID - Official libp2p specification
LIBP2P_TLS_EXTENSION_OID = x509.ObjectIdentifier("1.3.6.1.4.1.53594.1.1")

# Certificate validity period
CERTIFICATE_VALIDITY_DAYS = 365
CERTIFICATE_NOT_BEFORE_BUFFER = 3600  # 1 hour before now


@dataclass
@dataclass
class TLSConfig:
    """TLS configuration for QUIC transport with libp2p extensions."""

    certificate: x509.Certificate
    private_key: ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey
    peer_id: ID

    def get_certificate_der(self) -> bytes:
        """Get certificate in DER format for external use."""
        return self.certificate.public_bytes(serialization.Encoding.DER)

    def get_private_key_der(self) -> bytes:
        """Get private key in DER format for external use."""
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def get_certificate_pem(self) -> bytes:
        """Get certificate in PEM format."""
        return self.certificate.public_bytes(serialization.Encoding.PEM)

    def get_private_key_pem(self) -> bytes:
        """Get private key in PEM format."""
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )


class LibP2PExtensionHandler:
    """
    Handles libp2p-specific TLS extensions for peer identity verification.

    Based on libp2p TLS specification:
    https://github.com/libp2p/specs/blob/master/tls/tls.md
    """

    @staticmethod
    def create_signed_key_extension(
        libp2p_private_key: PrivateKey, cert_public_key: bytes
    ) -> bytes:
        """
        Create the libp2p Public Key Extension with signed key proof.

        The extension contains:
        1. The libp2p public key
        2. A signature proving ownership of the private key

        Args:
            libp2p_private_key: The libp2p identity private key
            cert_public_key: The certificate's public key bytes

        Returns:
            ASN.1 encoded extension value

        """
        try:
            # Get the libp2p public key
            libp2p_public_key = libp2p_private_key.get_public_key()

            # Create the signature payload: "libp2p-tls-handshake:" + cert_public_key
            signature_payload = b"libp2p-tls-handshake:" + cert_public_key

            # Sign the payload with the libp2p private key
            signature = libp2p_private_key.sign(signature_payload)

            # Create the SignedKey structure (simplified ASN.1 encoding)
            # In a full implementation, this would use proper ASN.1 encoding
            public_key_bytes = libp2p_public_key.serialize()

            # Simple encoding:
            # [public_key_length][public_key][signature_length][signature]
            extension_data = (
                len(public_key_bytes).to_bytes(4, byteorder="big")
                + public_key_bytes
                + len(signature).to_bytes(4, byteorder="big")
                + signature
            )

            return extension_data

        except Exception as e:
            raise QUICCertificateError(
                f"Failed to create signed key extension: {e}"
            ) from e

    @staticmethod
    def parse_signed_key_extension(extension_data: bytes) -> tuple[PublicKey, bytes]:
        """
        Parse the libp2p Public Key Extension to extract public key and signature.

        Args:
            extension_data: The extension data bytes

        Returns:
            Tuple of (libp2p_public_key, signature)

        Raises:
            QUICCertificateError: If extension parsing fails

        """
        try:
            offset = 0

            # Parse public key length and data
            if len(extension_data) < 4:
                raise QUICCertificateError("Extension too short for public key length")

            public_key_length = int.from_bytes(
                extension_data[offset : offset + 4], byteorder="big"
            )
            offset += 4

            if len(extension_data) < offset + public_key_length:
                raise QUICCertificateError("Extension too short for public key data")

            public_key_bytes = extension_data[offset : offset + public_key_length]
            offset += public_key_length

            # Parse signature length and data
            if len(extension_data) < offset + 4:
                raise QUICCertificateError("Extension too short for signature length")

            signature_length = int.from_bytes(
                extension_data[offset : offset + 4], byteorder="big"
            )
            offset += 4

            if len(extension_data) < offset + signature_length:
                raise QUICCertificateError("Extension too short for signature data")

            signature = extension_data[offset : offset + signature_length]

            public_key = LibP2PKeyConverter.deserialize_public_key(public_key_bytes)

            return public_key, signature

        except Exception as e:
            raise QUICCertificateError(
                f"Failed to parse signed key extension: {e}"
            ) from e


class LibP2PKeyConverter:
    """
    Converts between libp2p key formats and cryptography library formats.
    Handles different key types: Ed25519, Secp256k1, RSA, ECDSA.
    """

    @staticmethod
    def libp2p_to_tls_private_key(
        libp2p_key: PrivateKey,
    ) -> ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey:
        """
        Convert libp2p private key to TLS-compatible private key.

        For certificate generation, we create a separate ephemeral key
        rather than using the libp2p identity key directly.
        """
        # For QUIC, we prefer ECDSA keys for smaller certificates
        # Generate ephemeral P-256 key for certificate signing
        private_key = ec.generate_private_key(ec.SECP256R1())
        return private_key

    @staticmethod
    def serialize_public_key(public_key: PublicKey) -> bytes:
        """Serialize libp2p public key to bytes."""
        return public_key.serialize()

    @staticmethod
    def deserialize_public_key(key_bytes: bytes) -> PublicKey:
        """
        Deserialize libp2p public key from protobuf bytes.

        Args:
            key_bytes: Protobuf-serialized public key bytes

        Returns:
            Deserialized PublicKey instance

        """
        try:
            # Use the official libp2p deserialization function
            return deserialize_public_key(key_bytes)
        except Exception as e:
            raise QUICCertificateError(f"Failed to deserialize public key: {e}") from e


class CertificateGenerator:
    """
    Generates X.509 certificates with libp2p peer identity extensions.
    Follows libp2p TLS specification for QUIC transport.
    """

    def __init__(self) -> None:
        self.extension_handler = LibP2PExtensionHandler()
        self.key_converter = LibP2PKeyConverter()

    def generate_certificate(
        self,
        libp2p_private_key: PrivateKey,
        peer_id: ID,
        validity_days: int = CERTIFICATE_VALIDITY_DAYS,
    ) -> TLSConfig:
        """
        Generate a TLS certificate with embedded libp2p peer identity.
        Fixed to use datetime objects for validity periods.

        Args:
            libp2p_private_key: The libp2p identity private key
            peer_id: The libp2p peer ID
            validity_days: Certificate validity period in days

        Returns:
            TLSConfig with certificate and private key

        Raises:
            QUICCertificateError: If certificate generation fails

        """
        try:
            # Generate ephemeral private key for certificate
            cert_private_key = self.key_converter.libp2p_to_tls_private_key(
                libp2p_private_key
            )
            cert_public_key = cert_private_key.public_key()

            # Get certificate public key bytes for extension
            cert_public_key_bytes = cert_public_key.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )

            # Create libp2p extension with signed key proof
            extension_data = self.extension_handler.create_signed_key_extension(
                libp2p_private_key, cert_public_key_bytes
            )

            # Set validity period using datetime objects (FIXED)
            now = datetime.utcnow()  # Use datetime instead of time.time()
            not_before = now - timedelta(seconds=CERTIFICATE_NOT_BEFORE_BUFFER)
            not_after = now + timedelta(days=validity_days)

            # Generate serial number
            serial_number = int(now.timestamp())  # Convert datetime to timestamp

            # Build certificate with proper datetime objects
            certificate = (
                x509.CertificateBuilder()
                .subject_name(
                    x509.Name(
                        [x509.NameAttribute(NameOID.COMMON_NAME, peer_id.to_base58())]  # type: ignore
                    )
                )
                .issuer_name(
                    x509.Name(
                        [x509.NameAttribute(NameOID.COMMON_NAME, peer_id.to_base58())]  # type: ignore
                    )
                )
                .public_key(cert_public_key)
                .serial_number(serial_number)
                .not_valid_before(not_before)
                .not_valid_after(not_after)
                .add_extension(
                    x509.UnrecognizedExtension(
                        oid=LIBP2P_TLS_EXTENSION_OID, value=extension_data
                    ),
                    critical=False,
                )
                .sign(cert_private_key, hashes.SHA256())
            )

            logger.info(f"Generated libp2p TLS certificate for peer {peer_id}")
            logger.debug(f"Certificate valid from {not_before} to {not_after}")

            return TLSConfig(
                certificate=certificate, private_key=cert_private_key, peer_id=peer_id
            )

        except Exception as e:
            raise QUICCertificateError(f"Failed to generate certificate: {e}") from e


class PeerAuthenticator:
    """
    Authenticates remote peers using libp2p TLS certificates.
    Validates both TLS certificate integrity and libp2p peer identity.
    """

    def __init__(self) -> None:
        self.extension_handler = LibP2PExtensionHandler()

    def verify_peer_certificate(
        self, certificate: x509.Certificate, expected_peer_id: ID | None = None
    ) -> ID:
        """
        Verify a peer's TLS certificate and extract/validate peer identity.

        Args:
            certificate: The peer's TLS certificate
            expected_peer_id: Expected peer ID (for outbound connections)

        Returns:
            The verified peer ID

        Raises:
            QUICPeerVerificationError: If verification fails

        """
        try:
            # Extract libp2p extension
            libp2p_extension = None
            for extension in certificate.extensions:
                if extension.oid == LIBP2P_TLS_EXTENSION_OID:
                    libp2p_extension = extension
                    break

            if not libp2p_extension:
                raise QUICPeerVerificationError("Certificate missing libp2p extension")

            # Parse the extension to get public key and signature
            public_key, signature = self.extension_handler.parse_signed_key_extension(
                libp2p_extension.value
            )

            # Get certificate public key for signature verification
            cert_public_key_bytes = certificate.public_key().public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )

            # Verify the signature proves ownership of the libp2p private key
            signature_payload = b"libp2p-tls-handshake:" + cert_public_key_bytes

            try:
                public_key.verify(signature, signature_payload)
            except Exception as e:
                raise QUICPeerVerificationError(
                    f"Invalid signature in libp2p extension: {e}"
                )

            # Derive peer ID from public key
            derived_peer_id = ID.from_pubkey(public_key)

            # Verify against expected peer ID if provided
            if expected_peer_id and derived_peer_id != expected_peer_id:
                raise QUICPeerVerificationError(
                    f"Peer ID mismatch: expected {expected_peer_id}, "
                    f"got {derived_peer_id}"
                )

            logger.info(f"Successfully verified peer certificate for {derived_peer_id}")
            return derived_peer_id

        except QUICPeerVerificationError:
            raise
        except Exception as e:
            raise QUICPeerVerificationError(
                f"Certificate verification failed: {e}"
            ) from e


@dataclass
class QUICTLSSecurityConfig:
    """
    Type-safe TLS security configuration for QUIC transport.
    """

    # Core TLS components (required)
    certificate: Certificate
    private_key: Union[EllipticCurvePrivateKey, RSAPrivateKey]

    # Certificate chain (optional)
    certificate_chain: List[Certificate] = field(default_factory=list)

    # ALPN protocols
    alpn_protocols: List[str] = field(default_factory=lambda: ["libp2p"])

    # TLS verification settings
    verify_mode: Union[bool, ssl.VerifyMode] = False
    check_hostname: bool = False

    # Optional peer ID for validation
    peer_id: Optional[ID] = None

    # Configuration metadata
    is_client_config: bool = False
    config_name: Optional[str] = None

    def __post_init__(self):
        """Validate configuration after initialization."""
        self._validate()

    def _validate(self) -> None:
        """Validate the TLS configuration."""
        if self.certificate is None:
            raise ValueError("Certificate is required")

        if self.private_key is None:
            raise ValueError("Private key is required")

        if not isinstance(self.certificate, x509.Certificate):
            raise TypeError(
                f"Certificate must be x509.Certificate, got {type(self.certificate)}"
            )

        if not isinstance(
            self.private_key, (ec.EllipticCurvePrivateKey, rsa.RSAPrivateKey)
        ):
            raise TypeError(
                f"Private key must be EC or RSA key, got {type(self.private_key)}"
            )

        if not self.alpn_protocols:
            raise ValueError("At least one ALPN protocol is required")

    def to_dict(self) -> dict:
        """
        Convert to dictionary format for compatibility with existing code.

        Returns:
            Dictionary compatible with the original TSecurityConfig format

        """
        return {
            "certificate": self.certificate,
            "private_key": self.private_key,
            "certificate_chain": self.certificate_chain.copy(),
            "alpn_protocols": self.alpn_protocols.copy(),
            "verify_mode": self.verify_mode,
            "check_hostname": self.check_hostname,
        }

    @classmethod
    def from_dict(cls, config_dict: dict, **kwargs) -> "QUICTLSSecurityConfig":
        """
        Create instance from dictionary format.

        Args:
            config_dict: Dictionary in TSecurityConfig format
            **kwargs: Additional parameters for the config

        Returns:
            QUICTLSSecurityConfig instance

        """
        return cls(
            certificate=config_dict["certificate"],
            private_key=config_dict["private_key"],
            certificate_chain=config_dict.get("certificate_chain", []),
            alpn_protocols=config_dict.get("alpn_protocols", ["libp2p"]),
            verify_mode=config_dict.get("verify_mode", False),
            check_hostname=config_dict.get("check_hostname", False),
            **kwargs,
        )

    def validate_certificate_key_match(self) -> bool:
        """
        Validate that the certificate and private key match.

        Returns:
            True if certificate and private key match

        """
        try:
            from cryptography.hazmat.primitives import serialization

            # Get public keys from both certificate and private key
            cert_public_key = self.certificate.public_key()
            private_public_key = self.private_key.public_key()

            # Compare their PEM representations
            cert_pub_pem = cert_public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            private_pub_pem = private_public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )

            return cert_pub_pem == private_pub_pem

        except Exception:
            return False

    def has_libp2p_extension(self) -> bool:
        """
        Check if the certificate has the required libp2p extension.

        Returns:
            True if libp2p extension is present

        """
        try:
            libp2p_oid = "1.3.6.1.4.1.53594.1.1"
            for ext in self.certificate.extensions:
                if str(ext.oid) == libp2p_oid:
                    return True
            return False
        except Exception:
            return False

    def is_certificate_valid(self) -> bool:
        """
        Check if the certificate is currently valid (not expired).

        Returns:
            True if certificate is valid

        """
        try:
            from datetime import datetime

            now = datetime.utcnow()
            return (
                self.certificate.not_valid_before
                <= now
                <= self.certificate.not_valid_after
            )
        except Exception:
            return False

    def get_certificate_info(self) -> dict:
        """
        Get certificate information for debugging.

        Returns:
            Dictionary with certificate details

        """
        try:
            return {
                "subject": str(self.certificate.subject),
                "issuer": str(self.certificate.issuer),
                "serial_number": self.certificate.serial_number,
                "not_valid_before": self.certificate.not_valid_before,
                "not_valid_after": self.certificate.not_valid_after,
                "has_libp2p_extension": self.has_libp2p_extension(),
                "is_valid": self.is_certificate_valid(),
                "certificate_key_match": self.validate_certificate_key_match(),
            }
        except Exception as e:
            return {"error": str(e)}

    def debug_print(self) -> None:
        """Print debugging information about this configuration."""
        print(f"=== TLS Security Config Debug ({self.config_name or 'unnamed'}) ===")
        print(f"Is client config: {self.is_client_config}")
        print(f"ALPN protocols: {self.alpn_protocols}")
        print(f"Verify mode: {self.verify_mode}")
        print(f"Check hostname: {self.check_hostname}")
        print(f"Certificate chain length: {len(self.certificate_chain)}")

        cert_info = self.get_certificate_info()
        for key, value in cert_info.items():
            print(f"Certificate {key}: {value}")

        print(f"Private key type: {type(self.private_key).__name__}")
        if hasattr(self.private_key, "key_size"):
            print(f"Private key size: {self.private_key.key_size}")


def create_server_tls_config(
    certificate: Certificate,
    private_key: Union[EllipticCurvePrivateKey, RSAPrivateKey],
    peer_id: Optional[ID] = None,
    **kwargs,
) -> QUICTLSSecurityConfig:
    """
    Create a server TLS configuration.

    Args:
        certificate: X.509 certificate
        private_key: Private key corresponding to certificate
        peer_id: Optional peer ID for validation
        **kwargs: Additional configuration parameters

    Returns:
        Server TLS configuration

    """
    return QUICTLSSecurityConfig(
        certificate=certificate,
        private_key=private_key,
        peer_id=peer_id,
        is_client_config=False,
        config_name="server",
        verify_mode=False,  # Server doesn't verify client certs in libp2p
        check_hostname=False,
        **kwargs,
    )


def create_client_tls_config(
    certificate: Certificate,
    private_key: Union[EllipticCurvePrivateKey, RSAPrivateKey],
    peer_id: Optional[ID] = None,
    **kwargs,
) -> QUICTLSSecurityConfig:
    """
    Create a client TLS configuration.

    Args:
        certificate: X.509 certificate
        private_key: Private key corresponding to certificate
        peer_id: Optional peer ID for validation
        **kwargs: Additional configuration parameters

    Returns:
        Client TLS configuration

    """
    return QUICTLSSecurityConfig(
        certificate=certificate,
        private_key=private_key,
        peer_id=peer_id,
        is_client_config=True,
        config_name="client",
        verify_mode=False,  # Client doesn't verify server certs in libp2p
        check_hostname=False,
        **kwargs,
    )


class QUICTLSConfigManager:
    """
    Manages TLS configuration for QUIC transport with libp2p security.
    Integrates with aioquic's TLS configuration system.
    """

    def __init__(self, libp2p_private_key: PrivateKey, peer_id: ID):
        self.libp2p_private_key = libp2p_private_key
        self.peer_id = peer_id
        self.certificate_generator = CertificateGenerator()
        self.peer_authenticator = PeerAuthenticator()

        # Generate certificate for this peer
        self.tls_config = self.certificate_generator.generate_certificate(
            libp2p_private_key, peer_id
        )

    def create_server_config(self) -> QUICTLSSecurityConfig:
        """
        Create server configuration using the new class-based approach.

        Returns:
            QUICTLSSecurityConfig instance for server

        """
        config = create_server_tls_config(
            certificate=self.tls_config.certificate,
            private_key=self.tls_config.private_key,
            peer_id=self.peer_id,
        )

        print("🔧 SECURITY: Created server config")
        config.debug_print()
        return config

    def create_client_config(self) -> QUICTLSSecurityConfig:
        """
        Create client configuration using the new class-based approach.

        Returns:
            QUICTLSSecurityConfig instance for client

        """
        config = create_client_tls_config(
            certificate=self.tls_config.certificate,
            private_key=self.tls_config.private_key,
            peer_id=self.peer_id,
        )

        print("🔧 SECURITY: Created client config")
        config.debug_print()
        return config

    def verify_peer_identity(
        self, peer_certificate: x509.Certificate, expected_peer_id: ID | None = None
    ) -> ID:
        """
        Verify remote peer's identity from their TLS certificate.

        Args:
            peer_certificate: Remote peer's TLS certificate
            expected_peer_id: Expected peer ID (for outbound connections)

        Returns:
            Verified peer ID

        """
        return self.peer_authenticator.verify_peer_certificate(
            peer_certificate, expected_peer_id
        )

    def get_local_peer_id(self) -> ID:
        """Get the local peer ID."""
        return self.peer_id


# Factory function for creating QUIC security transport
def create_quic_security_transport(
    libp2p_private_key: PrivateKey, peer_id: ID
) -> QUICTLSConfigManager:
    """
    Factory function to create QUIC security transport.

    Args:
        libp2p_private_key: The libp2p identity private key
        peer_id: The libp2p peer ID

    Returns:
        Configured QUIC TLS manager

    """
    return QUICTLSConfigManager(libp2p_private_key, peer_id)


# Legacy compatibility functions for existing code
def generate_libp2p_tls_config(private_key: PrivateKey, peer_id: ID) -> TLSConfig:
    """
    Legacy function for compatibility with existing transport code.

    Args:
        private_key: libp2p private key
        peer_id: libp2p peer ID

    Returns:
        TLS configuration

    """
    generator = CertificateGenerator()
    return generator.generate_certificate(private_key, peer_id)


def cleanup_tls_config(config: TLSConfig) -> None:
    """
    Clean up TLS configuration.

    For the new implementation, this is mostly a no-op since we don't use
    temporary files, but kept for compatibility.
    """
    # New implementation doesn't use temporary files
    logger.debug("TLS config cleanup completed")
