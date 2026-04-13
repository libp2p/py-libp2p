from cryptography import x509
from cryptography.x509.oid import ObjectIdentifier

from libp2p.crypto.secp256k1 import create_new_key_pair as create_secp256k1
from libp2p.security.tls import certificate as certmod


def test_signedkey_asn1_roundtrip():
    pub = b"pub-bytes-example"
    sig = b"sig-bytes-example"
    der = certmod.encode_signed_key(pub, sig)
    sk = certmod.decode_signed_key(der)
    assert sk.public_key_bytes == b"pub-bytes-example"
    assert sk.signature == sig


def test_generate_certificate_has_libp2p_extension_noncritical():
    keypair = create_secp256k1()
    tmpl = certmod.create_cert_template()
    cert_pem, _ = certmod.generate_certificate(keypair.private_key, tmpl)
    cert = x509.load_pem_x509_certificate(cert_pem.encode())

    # Find extension
    found = False
    for ext in cert.extensions:
        if ext.oid == ObjectIdentifier("1.3.6.1.4.1.53594.1.1"):
            found = True
            assert ext.critical is False
            sk = certmod.decode_signed_key(ext.value.value)
            assert isinstance(sk.public_key_bytes, (bytes, bytearray))
            assert isinstance(sk.signature, (bytes, bytearray))
            break
    assert found, "libp2p extension missing"


def test_certificate_extensions_are_noncritical():
    """Verify BasicConstraints and KeyUsage are non-critical for Rust interop."""
    keypair = create_secp256k1()
    tmpl = certmod.create_cert_template()
    cert_pem, _ = certmod.generate_certificate(keypair.private_key, tmpl)
    cert = x509.load_pem_x509_certificate(cert_pem.encode())

    # Find and verify BasicConstraints and KeyUsage
    basic_constraints_found = False
    key_usage_found = False

    for ext in cert.extensions:
        if isinstance(ext.value, x509.BasicConstraints):
            basic_constraints_found = True
            assert ext.critical is False, (
                "BasicConstraints must be non-critical for Rust interop"
            )
        elif isinstance(ext.value, x509.KeyUsage):
            key_usage_found = True
            assert ext.critical is False, (
                "KeyUsage must be non-critical for Rust interop"
            )

    assert basic_constraints_found, "BasicConstraints extension missing"
    assert key_usage_found, "KeyUsage extension missing"


def test_verify_certificate_chain_extracts_host_public_key():
    # Generate cert for a new host key
    keypair = create_secp256k1()
    tmpl = certmod.create_cert_template()
    cert_pem, _ = certmod.generate_certificate(keypair.private_key, tmpl)
    cert = x509.load_pem_x509_certificate(cert_pem.encode())

    pub = certmod.verify_certificate_chain([cert])
    assert pub.to_bytes() == keypair.public_key.to_bytes()
