"""
TLS certificate utilities for libp2p.

This module provides certificate generation and verification functions
that embed libp2p peer identity information in X.509 extensions.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa
from cryptography.x509.oid import NameOID, ObjectIdentifier

from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.crypto.serialization import deserialize_public_key

# ALPN protocol for libp2p TLS
ALPN_PROTOCOL = "libp2p"

# Custom OID for libp2p peer identity extension (same as Rust implementation)
LIBP2P_EXTENSION_OID = ObjectIdentifier("1.3.6.1.4.1.53594.1.1")

# Prefix used when signing the TLS certificate public key with the libp2p host key
# to bind the X.509 certificate to the libp2p identity.
LIBP2P_CERT_PREFIX: bytes = b"libp2p-tls-handshake:"


@dataclass
class SignedKey:
    """Represents a signed public key embedded in certificate extension."""

    public_key_bytes: bytes
    signature: bytes


def encode_signed_key(public_key_bytes: bytes, signature: bytes) -> bytes:
    """
    ASN.1-encode the SignedKey structure for inclusion in the libp2p X.509 extension.

    Args:
        public_key_bytes: libp2p protobuf-encoded public key bytes
        signature: signature over prefix+certificate public key

    Returns:
        DER-encoded bytes representing the SignedKey sequence

    Raises:
        ValueError: If inputs are empty or exceed maximum allowed sizes

    """
    # Input validation
    if not public_key_bytes:
        raise ValueError("public_key_bytes cannot be empty")
    if not signature:
        raise ValueError("signature cannot be empty")

    # Reasonable size limits to prevent DoS
    MAX_KEY_SIZE = 1024 * 10  # 10KB
    MAX_SIG_SIZE = 1024 * 2  # 2KB

    if len(public_key_bytes) > MAX_KEY_SIZE:
        raise ValueError(f"public_key_bytes too large (max {MAX_KEY_SIZE} bytes)")
    if len(signature) > MAX_SIG_SIZE:
        raise ValueError(f"signature too large (max {MAX_SIG_SIZE} bytes)")

    # DER encoding helpers
    def _encode_len(n: int) -> bytes:
        if n < 0x80:
            return bytes([n])
        length_bytes = n.to_bytes((n.bit_length() + 7) // 8, byteorder="big")
        return bytes([0x80 | len(length_bytes)]) + length_bytes

    def _encode_octet_string(data: bytes) -> bytes:
        return bytes([0x04]) + _encode_len(len(data)) + data

    def _encode_sequence(content: bytes) -> bytes:
        return bytes([0x30]) + _encode_len(len(content)) + content

    content = _encode_octet_string(public_key_bytes) + _encode_octet_string(signature)
    return _encode_sequence(content)


def decode_signed_key(der_bytes: bytes) -> SignedKey:
    """
    Parse DER-encoded SignedKey from the libp2p X.509 extension value.

    Args:
        der_bytes: DER bytes for SignedKey

    Returns:
        Parsed SignedKey instance

    """

    # Minimal DER parser for: SEQUENCE { OCTET STRING, OCTET STRING }
    def _expect_byte(data: bytes, idx: int, b: int) -> int:
        if idx >= len(data) or data[idx] != b:
            raise ValueError("Invalid DER: unexpected tag")
        return idx + 1

    def _read_len(data: bytes, idx: int) -> tuple[int, int]:
        if idx >= len(data):
            raise ValueError("Invalid DER: truncated length")
        first = data[idx]
        idx += 1
        if first < 0x80:
            return first, idx
        num = first & 0x7F
        if idx + num > len(data):
            raise ValueError("Invalid DER: truncated long length")
        val = int.from_bytes(data[idx : idx + num], "big")
        return val, idx + num

    i = 0
    i = _expect_byte(der_bytes, i, 0x30)  # SEQUENCE
    seq_len, i = _read_len(der_bytes, i)
    end_seq = i + seq_len

    i = _expect_byte(der_bytes, i, 0x04)  # OCTET STRING
    pk_len, i = _read_len(der_bytes, i)
    if i + pk_len > len(der_bytes):
        raise ValueError("Invalid DER: truncated public key")
    pk_bytes = der_bytes[i : i + pk_len]
    i += pk_len

    i = _expect_byte(der_bytes, i, 0x04)  # OCTET STRING
    sig_len, i = _read_len(der_bytes, i)
    if i + sig_len > len(der_bytes):
        raise ValueError("Invalid DER: truncated signature")
    sig_bytes = der_bytes[i : i + sig_len]
    i += sig_len

    if i != end_seq:
        raise ValueError("Invalid DER: extra data in SignedKey")

    return SignedKey(public_key_bytes=pk_bytes, signature=sig_bytes)


def create_cert_template() -> x509.CertificateBuilder:
    """
    Create a certificate template for libp2p TLS certificates.

    Uses secure defaults:
    - Random 64-bit serial number
    - 1 hour backdating for not_before to handle clock skew
    - 100 year validity (since these are ephemeral, self-signed certs)
    - Basic Constraints: not a CA
    - Key Usage: digital signature only

    Returns:
        Certificate builder template with secure defaults

    """
    # Serial: random 64-bit value
    serial = int.from_bytes(os.urandom(8), "big")
    not_before = datetime.now(timezone.utc) - timedelta(hours=1)
    # ~100 years
    not_after = not_before + timedelta(days=365 * 100)

    # Create name attributes with explicit typing to satisfy strict type checker
    common_name_value: Any = "libp2p"
    subject_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, common_name_value)]
    )
    issuer_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, common_name_value)]
    )

    builder = (
        x509.CertificateBuilder()
        .serial_number(serial)
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .subject_name(subject_name)
        .issuer_name(issuer_name)
    )

    # Add Basic Constraints extension - not a CA
    builder = builder.add_extension(
        x509.BasicConstraints(ca=False, path_length=None), critical=True
    )

    # Add Key Usage - digital signature only
    builder = builder.add_extension(
        x509.KeyUsage(
            digital_signature=True,
            content_commitment=False,
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=False,
            crl_sign=False,
            encipher_only=False,
            decipher_only=False,
        ),
        critical=True,
    )
    return builder


def add_libp2p_extension(
    cert_builder: x509.CertificateBuilder, peer_public_key: PublicKey, signature: bytes
) -> x509.CertificateBuilder:
    """
    Add libp2p peer identity extension to certificate.

    Args:
        cert_builder: Certificate builder to modify
        peer_public_key: Peer's public key to embed
        signature: Signature over the certificate's public key

    Returns:
        Certificate builder with libp2p extension

    """
    sk_der = encode_signed_key(peer_public_key.serialize(), signature)
    ext = x509.UnrecognizedExtension(LIBP2P_EXTENSION_OID, sk_der)
    return cert_builder.add_extension(ext, critical=False)


def generate_certificate(
    private_key: PrivateKey, cert_template: x509.CertificateBuilder
) -> tuple[str, str]:
    """
    Generate a self-signed certificate with libp2p extensions.

    Args:
        private_key: Private key for signing
        cert_template: Certificate template

    Returns:
        Tuple of (certificate PEM, private key PEM)

    """
    # Generate an ephemeral TLS key (ECDSA P-256)
    tls_private_key = ec.generate_private_key(ec.SECP256R1())

    # Build SignedKey over the certificate's SubjectPublicKeyInfo
    spki_der = tls_private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signature = private_key.sign(LIBP2P_CERT_PREFIX + spki_der)

    builder = cert_template
    builder = builder.public_key(tls_private_key.public_key())
    # Self-signed
    builder = add_libp2p_extension(builder, private_key.get_public_key(), signature)
    certificate = builder.sign(
        private_key=tls_private_key,
        algorithm=hashes.SHA256(),
    )

    cert_pem = certificate.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = tls_private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return cert_pem, key_pem


def verify_certificate_chain(cert_chain: list[x509.Certificate]) -> PublicKey:
    """
    Verify certificate chain and extract peer public key from libp2p extension.

    Args:
        cert_chain: List of certificates in the chain

    Returns:
        Public key from libp2p extension

    Raises:
        ValueError: If verification fails, such as expired certificate,
                   missing extension, invalid signature, or unsupported key type.

    """
    if len(cert_chain) != 1:
        raise ValueError("expected one certificates in the chain")

    [cert] = cert_chain

    # 1) Validity window
    now = datetime.now(timezone.utc)
    not_before = getattr(cert, "not_valid_before_utc", None)
    not_after = getattr(cert, "not_valid_after_utc", None)
    if not_before is None:
        not_before = cert.not_valid_before.replace(tzinfo=timezone.utc)
    if not_after is None:
        not_after = cert.not_valid_after.replace(tzinfo=timezone.utc)
    if not_before > now or not_after < now:
        raise ValueError("certificate has expired or is not yet valid")

    # 2) Find libp2p extension
    ext_value: bytes | None = None
    for idx, ext in enumerate(cert.extensions):
        if ext.oid == LIBP2P_EXTENSION_OID:
            # Remove from unhandled critical list if necessary by re-creating cert
            # object is non-trivial here; we'll just parse value
            ext_value = (
                ext.value.value
                if isinstance(ext.value, x509.UnrecognizedExtension)
                else None
            )
            break
    if ext_value is None:
        raise ValueError("expected certificate to contain the key extension")

    # 3) Verify self-signature of the certificate
    pub = cert.public_key()
    # Verify self-signature with correct algorithm based on key type
    try:
        hash_alg = cert.signature_hash_algorithm
        if hash_alg is None:
            raise ValueError("Certificate signature hash algorithm is None")

        if isinstance(pub, ec.EllipticCurvePublicKey):
            pub.verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(hash_alg))
        elif isinstance(pub, rsa.RSAPublicKey):
            from cryptography.hazmat.primitives.asymmetric import padding

            pub.verify(
                cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), hash_alg
            )
        elif isinstance(pub, (ed25519.Ed25519PublicKey, ed448.Ed448PublicKey)):
            pub.verify(cert.signature, cert.tbs_certificate_bytes)
        elif isinstance(pub, dsa.DSAPublicKey):
            pub.verify(cert.signature, cert.tbs_certificate_bytes, hash_alg)
        else:
            raise ValueError(f"Unsupported key type for verification: {type(pub)}")
    except Exception as e:
        raise ValueError(f"certificate verification failed: {e}")

    # 4) Verify extension signature
    signed = decode_signed_key(ext_value)
    host_pub = deserialize_public_key(signed.public_key_bytes)

    spki_der = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    message = LIBP2P_CERT_PREFIX + spki_der
    if not host_pub.verify(message, signed.signature):
        raise ValueError("signature invalid")

    return host_pub


def pub_key_from_cert_chain(cert_chain: list[x509.Certificate]) -> PublicKey:
    """
    Extract public key from certificate chain.

    This is an alias for verify_certificate_chain for compatibility.

    Args:
        cert_chain: Certificate chain

    Returns:
        Public key

    """
    return verify_certificate_chain(cert_chain)


def generate_self_signed_cert() -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    """
    Generate a self-signed certificate for testing purposes.

    This is a utility function based on the guide examples.

    Returns:
        Tuple of (private key, certificate)

    """
    key = ec.generate_private_key(ec.SECP256R1())
    common_name_value: Any = "py-libp2p"
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name_value)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(int.from_bytes(os.urandom(8), "big"))
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return key, cert
