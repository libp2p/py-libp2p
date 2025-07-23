"""
TLS certificate utilities for libp2p.

This module provides certificate generation and verification functions
that embed libp2p peer identity information in X.509 extensions.
"""

from dataclasses import dataclass

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ObjectIdentifier

from libp2p.crypto.keys import PrivateKey, PublicKey

# ALPN protocol for libp2p TLS
ALPN_PROTOCOL = "libp2p"

# Custom OID for libp2p peer identity extension (same as Rust implementation)
LIBP2P_EXTENSION_OID = ObjectIdentifier("1.3.6.1.4.1.53594.1.1")


@dataclass
class SignedKey:
    """Represents a signed public key embedded in certificate extension."""

    public_key_bytes: bytes
    signature: bytes


def create_cert_template() -> x509.CertificateBuilder:
    """
    Create a certificate template for libp2p TLS certificates.

    Returns:
        Certificate builder template

    """
    raise NotImplementedError("TLS certificate template creation not implemented")


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
    raise NotImplementedError("libp2p extension addition not implemented")


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
    raise NotImplementedError("Certificate generation not implemented")


def verify_certificate_chain(cert_chain: list[x509.Certificate]) -> PublicKey:
    """
    Verify certificate chain and extract peer public key from libp2p extension.

    Args:
        cert_chain: List of certificates in the chain

    Returns:
        Public key from libp2p extension

    Raises:
        SecurityError: If verification fails

    """
    raise NotImplementedError("Certificate chain verification not implemented")


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
    raise NotImplementedError("Self-signed certificate generation not implemented")
