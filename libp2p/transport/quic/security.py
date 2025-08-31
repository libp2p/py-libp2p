"""
QUIC Security helpers implementation
"""

from dataclasses import dataclass, field
import logging
import ssl
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.x509.base import Certificate
from cryptography.x509.extensions import Extension, UnrecognizedExtension
from cryptography.x509.oid import NameOID

from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.crypto.serialization import deserialize_public_key
from libp2p.peer.id import ID

from .exceptions import (
    QUICCertificateError,
    QUICPeerVerificationError,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

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
        libp2p_private_key: PrivateKey,
        cert_public_key: bytes,
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
            Encoded extension value

        """
        try:
            # Get the libp2p public key
            libp2p_public_key = libp2p_private_key.get_public_key()

            # Create the signature payload: "libp2p-tls-handshake:" + cert_public_key
            signature_payload = b"libp2p-tls-handshake:" + cert_public_key

            # Sign the payload with the libp2p private key
            signature = libp2p_private_key.sign(signature_payload)

            # Get the public key bytes
            public_key_bytes = libp2p_public_key.serialize()

            # Create ASN.1 DER encoded structure (go-libp2p compatible)
            return LibP2PExtensionHandler._create_asn1_der_extension(
                public_key_bytes, signature
            )

        except Exception as e:
            raise QUICCertificateError(
                f"Failed to create signed key extension: {e}"
            ) from e

    @staticmethod
    def _create_asn1_der_extension(public_key_bytes: bytes, signature: bytes) -> bytes:
        """
        Create ASN.1 DER encoded extension (go-libp2p compatible).

        Structure:
        SEQUENCE {
            publicKey OCTET STRING,
            signature OCTET STRING
        }
        """
        # Encode public key as OCTET STRING
        pubkey_octets = LibP2PExtensionHandler._encode_der_octet_string(
            public_key_bytes
        )

        # Encode signature as OCTET STRING
        sig_octets = LibP2PExtensionHandler._encode_der_octet_string(signature)

        # Combine into SEQUENCE
        sequence_content = pubkey_octets + sig_octets

        # Encode as SEQUENCE
        return LibP2PExtensionHandler._encode_der_sequence(sequence_content)

    @staticmethod
    def _encode_der_length(length: int) -> bytes:
        """Encode length in DER format."""
        if length < 128:
            # Short form
            return bytes([length])
        else:
            # Long form
            length_bytes = length.to_bytes(
                (length.bit_length() + 7) // 8, byteorder="big"
            )
            return bytes([0x80 | len(length_bytes)]) + length_bytes

    @staticmethod
    def _encode_der_octet_string(data: bytes) -> bytes:
        """Encode data as DER OCTET STRING."""
        return (
            bytes([0x04]) + LibP2PExtensionHandler._encode_der_length(len(data)) + data
        )

    @staticmethod
    def _encode_der_sequence(data: bytes) -> bytes:
        """Encode data as DER SEQUENCE."""
        return (
            bytes([0x30]) + LibP2PExtensionHandler._encode_der_length(len(data)) + data
        )

    @staticmethod
    def parse_signed_key_extension(
        extension: Extension[Any],
    ) -> tuple[PublicKey, bytes]:
        """
        Parse the libp2p Public Key Extension with support for all crypto types.
        Handles both ASN.1 DER format (from go-libp2p) and simple binary format.
        """
        try:
            logger.debug(f"🔍 Extension type: {type(extension)}")
            logger.debug(f"🔍 Extension.value type: {type(extension.value)}")

            # Extract the raw bytes from the extension
            if isinstance(extension.value, UnrecognizedExtension):
                raw_bytes = extension.value.value
                logger.debug(
                    "🔍 Extension is UnrecognizedExtension, using .value property"
                )
            else:
                raw_bytes = extension.value
                logger.debug("🔍 Extension.value is already bytes")

            logger.debug(f"🔍 Total extension length: {len(raw_bytes)} bytes")
            logger.debug(f"🔍 Extension hex (first 50 bytes): {raw_bytes[:50].hex()}")

            if not isinstance(raw_bytes, bytes):
                raise QUICCertificateError(f"Expected bytes, got {type(raw_bytes)}")

            # Check if this is ASN.1 DER encoded (from go-libp2p)
            if len(raw_bytes) >= 4 and raw_bytes[0] == 0x30:
                logger.debug("🔍 Detected ASN.1 DER encoding")
                return LibP2PExtensionHandler._parse_asn1_der_extension(raw_bytes)
            else:
                logger.debug("🔍 Using simple binary format parsing")
                return LibP2PExtensionHandler._parse_simple_binary_extension(raw_bytes)

        except Exception as e:
            logger.debug(f"❌ Extension parsing failed: {e}")
            import traceback

            logger.debug(f"❌ Traceback: {traceback.format_exc()}")
            raise QUICCertificateError(
                f"Failed to parse signed key extension: {e}"
            ) from e

    @staticmethod
    def _parse_asn1_der_extension(raw_bytes: bytes) -> tuple[PublicKey, bytes]:
        """
        Parse ASN.1 DER encoded extension (go-libp2p format).

        The structure is typically:
        SEQUENCE {
            publicKey OCTET STRING,
            signature OCTET STRING
        }
        """
        try:
            offset = 0

            # Parse SEQUENCE tag
            if raw_bytes[offset] != 0x30:
                raise QUICCertificateError(
                    f"Expected SEQUENCE tag (0x30), got {raw_bytes[offset]:02x}"
                )
            offset += 1

            # Parse SEQUENCE length
            seq_length, length_bytes = LibP2PExtensionHandler._parse_der_length(
                raw_bytes[offset:]
            )
            offset += length_bytes
            logger.debug(f"🔍 SEQUENCE length: {seq_length} bytes")

            # Parse first OCTET STRING (public key)
            if raw_bytes[offset] != 0x04:
                raise QUICCertificateError(
                    f"Expected OCTET STRING tag (0x04), got {raw_bytes[offset]:02x}"
                )
            offset += 1

            pubkey_length, length_bytes = LibP2PExtensionHandler._parse_der_length(
                raw_bytes[offset:]
            )
            offset += length_bytes
            logger.debug(f"🔍 Public key length: {pubkey_length} bytes")

            if len(raw_bytes) < offset + pubkey_length:
                raise QUICCertificateError("Extension too short for public key data")

            public_key_bytes = raw_bytes[offset : offset + pubkey_length]
            offset += pubkey_length

            # Parse second OCTET STRING (signature)
            if offset < len(raw_bytes) and raw_bytes[offset] == 0x04:
                offset += 1
                sig_length, length_bytes = LibP2PExtensionHandler._parse_der_length(
                    raw_bytes[offset:]
                )
                offset += length_bytes
                logger.debug(f"🔍 Signature length: {sig_length} bytes")

                if len(raw_bytes) < offset + sig_length:
                    raise QUICCertificateError("Extension too short for signature data")

                signature_data = raw_bytes[offset : offset + sig_length]
            else:
                # Signature might be the remaining bytes
                signature_data = raw_bytes[offset:]

            logger.debug(f"🔍 Public key data length: {len(public_key_bytes)} bytes")
            logger.debug(f"🔍 Signature data length: {len(signature_data)} bytes")

            # Deserialize the public key
            public_key = LibP2PKeyConverter.deserialize_public_key(public_key_bytes)
            logger.debug(f"🔍 Successfully deserialized public key: {type(public_key)}")

            # Extract signature based on key type
            signature = LibP2PExtensionHandler._extract_signature_by_key_type(
                public_key, signature_data
            )

            return public_key, signature

        except Exception as e:
            raise QUICCertificateError(
                f"Failed to parse ASN.1 DER extension: {e}"
            ) from e

    @staticmethod
    def _parse_der_length(data: bytes) -> tuple[int, int]:
        """
        Parse DER length encoding.
        Returns (length_value, bytes_consumed).
        """
        if not data:
            raise QUICCertificateError("No data for DER length")

        first_byte = data[0]

        # Short form (length < 128)
        if first_byte < 0x80:
            return first_byte, 1

        # Long form
        num_bytes = first_byte & 0x7F
        if len(data) < 1 + num_bytes:
            raise QUICCertificateError("Insufficient data for DER long form length")

        length = 0
        for i in range(1, num_bytes + 1):
            length = (length << 8) | data[i]

        return length, 1 + num_bytes

    @staticmethod
    def _parse_simple_binary_extension(raw_bytes: bytes) -> tuple[PublicKey, bytes]:
        """
        Parse simple binary format extension (original py-libp2p format).
        Format: [4-byte pubkey length][pubkey][4-byte sig length][signature]
        """
        offset = 0

        # Parse public key length and data
        if len(raw_bytes) < 4:
            raise QUICCertificateError("Extension too short for public key length")

        public_key_length = int.from_bytes(
            raw_bytes[offset : offset + 4], byteorder="big"
        )
        logger.debug(f"🔍 Public key length: {public_key_length} bytes")
        offset += 4

        if len(raw_bytes) < offset + public_key_length:
            raise QUICCertificateError("Extension too short for public key data")

        public_key_bytes = raw_bytes[offset : offset + public_key_length]
        offset += public_key_length

        # Parse signature length and data
        if len(raw_bytes) < offset + 4:
            raise QUICCertificateError("Extension too short for signature length")

        signature_length = int.from_bytes(
            raw_bytes[offset : offset + 4], byteorder="big"
        )
        logger.debug(f"🔍 Signature length: {signature_length} bytes")
        offset += 4

        if len(raw_bytes) < offset + signature_length:
            raise QUICCertificateError("Extension too short for signature data")

        signature_data = raw_bytes[offset : offset + signature_length]

        # Deserialize the public key
        public_key = LibP2PKeyConverter.deserialize_public_key(public_key_bytes)
        logger.debug(f"🔍 Successfully deserialized public key: {type(public_key)}")

        # Extract signature based on key type
        signature = LibP2PExtensionHandler._extract_signature_by_key_type(
            public_key, signature_data
        )

        return public_key, signature

    @staticmethod
    def _extract_signature_by_key_type(
        public_key: PublicKey, signature_data: bytes
    ) -> bytes:
        """
        Extract the actual signature from signature_data based on the key type.
        Different crypto libraries have different signature formats.
        """
        if not hasattr(public_key, "get_type"):
            logger.debug("⚠️  Public key has no get_type method, using signature as-is")
            return signature_data

        key_type = public_key.get_type()
        key_type_name = key_type.name if hasattr(key_type, "name") else str(key_type)
        logger.debug(f"🔍 Processing signature for key type: {key_type_name}")

        # Handle different key types
        if key_type_name == "Ed25519":
            return LibP2PExtensionHandler._extract_ed25519_signature(signature_data)

        elif key_type_name == "Secp256k1":
            return LibP2PExtensionHandler._extract_secp256k1_signature(signature_data)

        elif key_type_name == "RSA":
            return LibP2PExtensionHandler._extract_rsa_signature(signature_data)

        elif key_type_name in ["ECDSA", "ECC_P256"]:
            return LibP2PExtensionHandler._extract_ecdsa_signature(signature_data)

        else:
            logger.debug(
                f"⚠️  Unknown key type {key_type_name}, using generic extraction"
            )
            return LibP2PExtensionHandler._extract_generic_signature(signature_data)

    @staticmethod
    def _extract_ed25519_signature(signature_data: bytes) -> bytes:
        """Extract Ed25519 signature (must be exactly 64 bytes)."""
        logger.debug("🔧 Extracting Ed25519 signature")

        if len(signature_data) == 64:
            logger.debug("✅ Ed25519 signature is already 64 bytes")
            return signature_data

        logger.debug(
            f"⚠️  Ed25519 signature is {len(signature_data)} bytes, extracting 64 bytes"
        )

        # Look for the payload marker and extract signature before it
        payload_marker = b"libp2p-tls-handshake:"
        marker_index = signature_data.find(payload_marker)

        if marker_index >= 64:
            # The signature is likely the first 64 bytes before the payload
            signature = signature_data[:64]
            logger.debug("🔧 Using first 64 bytes as Ed25519 signature")
            return signature

        elif marker_index > 0 and marker_index == 64:
            # Perfect case: signature is exactly before the marker
            signature = signature_data[:marker_index]
            logger.debug(f"🔧 Using {len(signature)} bytes before payload marker")
            return signature

        else:
            # Fallback: try to extract first 64 bytes
            if len(signature_data) >= 64:
                signature = signature_data[:64]
                logger.debug("🔧 Fallback: using first 64 bytes")
                return signature
            else:
                logger.debug(
                    f"Cannot extract 64 bytes from {len(signature_data)} byte signature"
                )
                return signature_data

    @staticmethod
    def _extract_secp256k1_signature(signature_data: bytes) -> bytes:
        """
        Extract Secp256k1 signature. Secp256k1 can use either DER-encoded
        or raw format depending on the implementation.
        """
        logger.debug("🔧 Extracting Secp256k1 signature")

        # Look for payload marker to separate signature from payload
        payload_marker = b"libp2p-tls-handshake:"
        marker_index = signature_data.find(payload_marker)

        if marker_index > 0:
            signature = signature_data[:marker_index]
            logger.debug(f"🔧 Using {len(signature)} bytes before payload marker")

            # Check if it's DER-encoded (starts with 0x30)
            if len(signature) >= 2 and signature[0] == 0x30:
                logger.debug("🔍 Secp256k1 signature appears to be DER-encoded")
                return LibP2PExtensionHandler._validate_der_signature(signature)
            else:
                logger.debug("🔍 Secp256k1 signature appears to be raw format")
                return signature
        else:
            # No marker found, check if the whole data is DER-encoded
            if len(signature_data) >= 2 and signature_data[0] == 0x30:
                logger.debug(
                    "🔍 Secp256k1 signature appears to be DER-encoded (no marker)"
                )
                return LibP2PExtensionHandler._validate_der_signature(signature_data)
            else:
                logger.debug("🔍 Using Secp256k1 signature data as-is")
                return signature_data

    @staticmethod
    def _extract_rsa_signature(signature_data: bytes) -> bytes:
        """
        Extract RSA signature.
        RSA signatures are typically raw bytes with length matching the key size.
        """
        logger.debug("🔧 Extracting RSA signature")

        # Look for payload marker to separate signature from payload
        payload_marker = b"libp2p-tls-handshake:"
        marker_index = signature_data.find(payload_marker)

        if marker_index > 0:
            signature = signature_data[:marker_index]
            logger.debug(
                f"🔧 Using {len(signature)} bytes before payload marker for RSA"
            )
            return signature
        else:
            logger.debug("🔍 Using RSA signature data as-is")
            return signature_data

    @staticmethod
    def _extract_ecdsa_signature(signature_data: bytes) -> bytes:
        """
        Extract ECDSA signature (typically DER-encoded ASN.1).
        ECDSA signatures start with 0x30 (ASN.1 SEQUENCE).
        """
        logger.debug("🔧 Extracting ECDSA signature")

        # Look for payload marker to separate signature from payload
        payload_marker = b"libp2p-tls-handshake:"
        marker_index = signature_data.find(payload_marker)

        if marker_index > 0:
            signature = signature_data[:marker_index]
            logger.debug(f"🔧 Using {len(signature)} bytes before payload marker")

            # Validate DER encoding for ECDSA
            if len(signature) >= 2 and signature[0] == 0x30:
                return LibP2PExtensionHandler._validate_der_signature(signature)
            else:
                logger.debug(
                    "⚠️  ECDSA signature doesn't start with DER header, using as-is"
                )
                return signature
        else:
            # Check if the whole data is DER-encoded
            if len(signature_data) >= 2 and signature_data[0] == 0x30:
                logger.debug("🔍 ECDSA signature appears to be DER-encoded (no marker)")
                return LibP2PExtensionHandler._validate_der_signature(signature_data)
            else:
                logger.debug("🔍 Using ECDSA signature data as-is")
                return signature_data

    @staticmethod
    def _extract_generic_signature(signature_data: bytes) -> bytes:
        """
        Generic signature extraction for unknown key types.
        Tries to detect DER encoding or extract based on payload marker.
        """
        logger.debug("🔧 Extracting signature using generic method")

        # Look for payload marker to separate signature from payload
        payload_marker = b"libp2p-tls-handshake:"
        marker_index = signature_data.find(payload_marker)

        if marker_index > 0:
            signature = signature_data[:marker_index]
            logger.debug(f"🔧 Using {len(signature)} bytes before payload marker")

            # Check if it's DER-encoded
            if len(signature) >= 2 and signature[0] == 0x30:
                return LibP2PExtensionHandler._validate_der_signature(signature)
            else:
                return signature
        else:
            # Check if the whole data is DER-encoded
            if len(signature_data) >= 2 and signature_data[0] == 0x30:
                logger.debug(
                    "🔍 Generic signature appears to be DER-encoded (no marker)"
                )
                return LibP2PExtensionHandler._validate_der_signature(signature_data)
            else:
                logger.debug("🔍 Using signature data as-is")
                return signature_data

    @staticmethod
    def _validate_der_signature(signature: bytes) -> bytes:
        """
        Validate and potentially fix DER-encoded signatures.
        DER signatures have the format: 30 [length] ...
        """
        if len(signature) < 2:
            return signature

        if signature[0] != 0x30:
            logger.debug("⚠️  Signature doesn't start with DER SEQUENCE tag")
            return signature

        # Get the DER length
        der_length = signature[1]
        expected_total_length = der_length + 2

        logger.debug(
            f"🔍 DER signature: length byte = {der_length}, "
            f"expected total = {expected_total_length}, "
            f"actual length = {len(signature)}"
        )

        if len(signature) == expected_total_length:
            logger.debug("✅ DER signature length is correct")
            return signature
        elif len(signature) > expected_total_length:
            logger.debug(
                "Truncating DER signature from "
                f"{len(signature)} to {expected_total_length} bytes"
            )
            return signature[:expected_total_length]
        else:
            logger.debug("DER signature is shorter than expected, using as-is")
            return signature


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

            from datetime import datetime, timedelta, timezone

            now = datetime.now(timezone.utc)
            not_before = now - timedelta(minutes=1)
            not_after = now + timedelta(days=validity_days)

            # Generate serial number
            serial_number = int(now.timestamp())

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
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)

            if certificate.not_valid_after_utc < now:
                raise QUICPeerVerificationError("Certificate has expired")

            if certificate.not_valid_before_utc > now:
                raise QUICPeerVerificationError("Certificate not yet valid")

            # Extract libp2p extension
            libp2p_extension = None
            for extension in certificate.extensions:
                if extension.oid == LIBP2P_TLS_EXTENSION_OID:
                    libp2p_extension = extension
                    break

            if not libp2p_extension:
                raise QUICPeerVerificationError("Certificate missing libp2p extension")

            assert libp2p_extension.value is not None
            logger.debug(f"Extension type: {type(libp2p_extension)}")
            logger.debug(f"Extension value type: {type(libp2p_extension.value)}")
            if hasattr(libp2p_extension.value, "__len__"):
                logger.debug(f"Extension value length: {len(libp2p_extension.value)}")
            logger.debug(f"Extension value: {libp2p_extension.value}")
            # Parse the extension to get public key and signature
            public_key, signature = self.extension_handler.parse_signed_key_extension(
                libp2p_extension
            )

            # Get certificate public key for signature verification
            cert_public_key_bytes = certificate.public_key().public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )

            # Verify the signature proves ownership of the libp2p private key
            signature_payload = b"libp2p-tls-handshake:" + cert_public_key_bytes

            try:
                public_key.verify(signature_payload, signature)
            except Exception as e:
                raise QUICPeerVerificationError(
                    f"Invalid signature in libp2p extension: {e}"
                )

            # Derive peer ID from public key
            derived_peer_id = ID.from_pubkey(public_key)

            # Verify against expected peer ID if provided
            if expected_peer_id and derived_peer_id != expected_peer_id:
                logger.debug(f"Expected Peer id: {expected_peer_id}")
                logger.debug(f"Derived Peer ID: {derived_peer_id}")
                raise QUICPeerVerificationError(
                    f"Peer ID mismatch: expected {expected_peer_id}, "
                    f"got {derived_peer_id}"
                )

            logger.debug(
                f"Successfully verified peer certificate for {derived_peer_id}"
            )
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
    private_key: EllipticCurvePrivateKey | RSAPrivateKey

    # Certificate chain (optional)
    certificate_chain: list[Certificate] = field(default_factory=list)

    # ALPN protocols
    alpn_protocols: list[str] = field(default_factory=lambda: ["libp2p"])

    # TLS verification settings
    verify_mode: ssl.VerifyMode = ssl.CERT_NONE
    check_hostname: bool = False
    request_client_certificate: bool = False

    # Optional peer ID for validation
    peer_id: ID | None = None

    # Configuration metadata
    is_client_config: bool = False
    config_name: str | None = None

    def __post_init__(self) -> None:
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
            for ext in self.certificate.extensions:
                if ext.oid == LIBP2P_TLS_EXTENSION_OID:
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
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            not_before = self.certificate.not_valid_before_utc
            not_after = self.certificate.not_valid_after_utc

            return not_before <= now <= not_after
        except Exception:
            return False

    def get_certificate_info(self) -> dict[Any, Any]:
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
                "not_valid_before_utc": self.certificate.not_valid_before_utc,
                "not_valid_after_utc": self.certificate.not_valid_after_utc,
                "has_libp2p_extension": self.has_libp2p_extension(),
                "is_valid": self.is_certificate_valid(),
                "certificate_key_match": self.validate_certificate_key_match(),
            }
        except Exception as e:
            return {"error": str(e)}

    def debug_config(self) -> None:
        """logger.debug debugging information about this configuration."""
        logger.debug(
            f"=== TLS Security Config Debug ({self.config_name or 'unnamed'}) ==="
        )
        logger.debug(f"Is client config: {self.is_client_config}")
        logger.debug(f"ALPN protocols: {self.alpn_protocols}")
        logger.debug(f"Verify mode: {self.verify_mode}")
        logger.debug(f"Check hostname: {self.check_hostname}")
        logger.debug(f"Certificate chain length: {len(self.certificate_chain)}")

        cert_info: dict[Any, Any] = self.get_certificate_info()
        for key, value in cert_info.items():
            logger.debug(f"Certificate {key}: {value}")

        logger.debug(f"Private key type: {type(self.private_key).__name__}")
        if hasattr(self.private_key, "key_size"):
            logger.debug(f"Private key size: {self.private_key.key_size}")


def create_server_tls_config(
    certificate: Certificate,
    private_key: EllipticCurvePrivateKey | RSAPrivateKey,
    peer_id: ID | None = None,
    **kwargs: Any,
) -> QUICTLSSecurityConfig:
    """
    Create a server TLS configuration.

    Args:
        certificate: X.509 certificate
        private_key: Private key corresponding to certificate
        peer_id: Optional peer ID for validation
        kwargs: Additional configuration parameters

    Returns:
        Server TLS configuration

    """
    return QUICTLSSecurityConfig(
        certificate=certificate,
        private_key=private_key,
        peer_id=peer_id,
        is_client_config=False,
        config_name="server",
        verify_mode=ssl.CERT_NONE,
        check_hostname=False,
        request_client_certificate=True,
        **kwargs,
    )


def create_client_tls_config(
    certificate: Certificate,
    private_key: EllipticCurvePrivateKey | RSAPrivateKey,
    peer_id: ID | None = None,
    **kwargs: Any,
) -> QUICTLSSecurityConfig:
    """
    Create a client TLS configuration.

    Args:
        certificate: X.509 certificate
        private_key: Private key corresponding to certificate
        peer_id: Optional peer ID for validation
        kwargs: Additional configuration parameters

    Returns:
        Client TLS configuration

    """
    return QUICTLSSecurityConfig(
        certificate=certificate,
        private_key=private_key,
        peer_id=peer_id,
        is_client_config=True,
        config_name="client",
        verify_mode=ssl.CERT_NONE,
        check_hostname=False,
        **kwargs,
    )


class QUICTLSConfigManager:
    """
    Manages TLS configuration for QUIC transport with libp2p security.
    Integrates with aioquic's TLS configuration system.
    """

    def __init__(self, libp2p_private_key: PrivateKey, peer_id: ID) -> None:
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
