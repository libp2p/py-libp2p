"""
Tests for QUIC AutoTLS integration.
"""

from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.quic.security import (
    LIBP2P_TLS_EXTENSION_OID,
    QUICTLSConfigManager,
)
import libp2p.utils.paths


def _write_cached_autotls_certificate(
    cert_path, key_path
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    now = datetime.now(timezone.utc)
    private_key = ec.generate_private_key(ec.SECP256R1())

    subject = issuer = x509.Name.from_rfc4514_string("CN=quic-autotls-test.local")
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .sign(private_key=private_key, algorithm=hashes.SHA256())
    )

    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    return certificate, private_key


def test_quic_tls_config_manager_loads_cached_autotls_certificate(
    tmp_path, monkeypatch
) -> None:
    cert_path = tmp_path / "autotls-cert.pem"
    key_path = tmp_path / "autotls-key.pem"
    expected_certificate, expected_private_key = _write_cached_autotls_certificate(
        cert_path, key_path
    )

    monkeypatch.setattr(libp2p.utils.paths, "AUTOTLS_CERT_PATH", cert_path)
    monkeypatch.setattr(libp2p.utils.paths, "AUTOTLS_KEY_PATH", key_path)

    libp2p_key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(libp2p_key_pair.public_key)

    manager = QUICTLSConfigManager(
        libp2p_private_key=libp2p_key_pair.private_key,
        peer_id=peer_id,
        enable_autotls=True,
    )

    assert manager.enable_autotls is True
    assert manager.tls_config.peer_id == peer_id
    assert manager.tls_config.certificate.fingerprint(
        hashes.SHA256()
    ) == expected_certificate.fingerprint(hashes.SHA256())
    assert isinstance(manager.tls_config.private_key, ec.EllipticCurvePrivateKey)
    assert (
        manager.tls_config.private_key.private_numbers()
        == expected_private_key.private_numbers()
    )


def test_quic_tls_config_manager_falls_back_to_self_signed_without_cache(
    tmp_path, monkeypatch
) -> None:
    cert_path = tmp_path / "missing-autotls-cert.pem"
    key_path = tmp_path / "missing-autotls-key.pem"

    monkeypatch.setattr(libp2p.utils.paths, "AUTOTLS_CERT_PATH", cert_path)
    monkeypatch.setattr(libp2p.utils.paths, "AUTOTLS_KEY_PATH", key_path)

    libp2p_key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(libp2p_key_pair.public_key)

    manager = QUICTLSConfigManager(
        libp2p_private_key=libp2p_key_pair.private_key,
        peer_id=peer_id,
        enable_autotls=True,
    )

    assert manager.enable_autotls is True
    assert manager.tls_config.peer_id == peer_id
    assert not cert_path.exists()
    assert not key_path.exists()
    assert (
        manager.tls_config.certificate.issuer == manager.tls_config.certificate.subject
    )

    # Self-signed libp2p certs include the libp2p TLS extension.
    extension = manager.tls_config.certificate.extensions.get_extension_for_oid(
        LIBP2P_TLS_EXTENSION_OID
    )
    assert extension is not None
