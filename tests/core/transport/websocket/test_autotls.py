"""
Simple AutoTLS unit tests for WebSocket transport.

These tests validate the basic AutoTLS functionality with minimal dependencies.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

import pytest

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.websocket.autotls import (
    AutoTLSConfig,
    FileCertificateStorage,
    TLSCertificate,
)
from libp2p.transport.websocket.tls_config import (
    CertificateConfig,
    CertificateValidationMode,
    TLSConfig,
    WebSocketTLSConfig,
)


class TestTLSCertificate:
    """Test TLSCertificate basic functionality."""

    def test_certificate_creation(self) -> None:
        """Test creating a TLS certificate."""
        key_pair = create_new_key_pair()
        peer_id = ID.from_pubkey(key_pair.public_key)

        cert_pem = "-----BEGIN CERTIFICATE-----\nMOCK_CERT\n-----END CERTIFICATE-----"
        key_pem = "-----BEGIN PRIVATE KEY-----\nMOCK_KEY\n-----END PRIVATE KEY-----"
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        cert = TLSCertificate(
            cert_pem=cert_pem,
            key_pem=key_pem,
            peer_id=peer_id,
            domain="test.local",
            expires_at=expires_at,
        )

        assert cert.cert_pem == cert_pem
        assert cert.key_pem == key_pem
        assert cert.peer_id == peer_id
        assert cert.domain == "test.local"
        assert not cert.is_expired
        assert not cert.is_expiring_soon(24)

    def test_certificate_expiry_check(self) -> None:
        """Test certificate expiry checks."""
        key_pair = create_new_key_pair()
        peer_id = ID.from_pubkey(key_pair.public_key)

        # Expired certificate
        expired_cert = TLSCertificate(
            cert_pem="-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----",
            key_pem="-----BEGIN PRIVATE KEY-----\nMOCK\n-----END PRIVATE KEY-----",
            peer_id=peer_id,
            domain="test.local",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        assert expired_cert.is_expired

        # Certificate expiring soon
        expiring_cert = TLSCertificate(
            cert_pem="-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----",
            key_pem="-----BEGIN PRIVATE KEY-----\nMOCK\n-----END PRIVATE KEY-----",
            peer_id=peer_id,
            domain="test.local",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
        )
        assert expiring_cert.is_expiring_soon(24)
        assert not expiring_cert.is_expiring_soon(1)


class TestFileCertificateStorage:
    """Test FileCertificateStorage basic functionality."""

    @pytest.mark.trio
    async def test_storage_save_and_load(self) -> None:
        """Test saving and loading certificates."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = FileCertificateStorage(Path(temp_dir))
            key_pair = create_new_key_pair()
            peer_id = ID.from_pubkey(key_pair.public_key)

            cert_pem = (
                "-----BEGIN CERTIFICATE-----\nMOCK_CERT\n-----END CERTIFICATE-----"
            )
            key_pem = "-----BEGIN PRIVATE KEY-----\nMOCK_KEY\n-----END PRIVATE KEY-----"
            expires_at = datetime.now(timezone.utc) + timedelta(days=7)

            cert = TLSCertificate(
                cert_pem=cert_pem,
                key_pem=key_pem,
                peer_id=peer_id,
                domain="test.local",
                expires_at=expires_at,
            )

            # Save certificate
            await storage.store_certificate(cert)

            # Load certificate
            loaded = await storage.load_certificate(peer_id, "test.local")

            assert loaded is not None
            assert loaded.cert_pem == cert.cert_pem
            assert loaded.key_pem == cert.key_pem
            assert loaded.domain == cert.domain

    @pytest.mark.trio
    async def test_storage_delete(self) -> None:
        """Test deleting certificates."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = FileCertificateStorage(Path(temp_dir))
            key_pair = create_new_key_pair()
            peer_id = ID.from_pubkey(key_pair.public_key)

            cert = TLSCertificate(
                cert_pem="-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----",
                key_pem="-----BEGIN PRIVATE KEY-----\nMOCK\n-----END PRIVATE KEY-----",
                peer_id=peer_id,
                domain="test.local",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )

            # Save and then delete
            await storage.store_certificate(cert)
            await storage.delete_certificate(peer_id, "test.local")

            # Should not be able to load deleted certificate
            loaded = await storage.load_certificate(peer_id, "test.local")
            assert loaded is None


class TestAutoTLSConfig:
    """Test AutoTLSConfig basic functionality."""

    def test_config_creation(self) -> None:
        """Test creating AutoTLS configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = AutoTLSConfig(
                enabled=True,
                storage_path=Path(temp_dir),
                default_domain="test.local",
                cert_validity_days=7,
                renewal_threshold_hours=48,
            )

            assert config.enabled is True
            assert config.default_domain == "test.local"
            assert config.cert_validity_days == 7
            assert config.renewal_threshold_hours == 48


class TestTLSConfig:
    """Test TLSConfig basic functionality."""

    def test_tls_config_creation(self) -> None:
        """Test creating TLS configuration."""
        cert_config = CertificateConfig(
            cert_file="cert.pem",
            key_file="key.pem",
            validation_mode=CertificateValidationMode.BASIC,
        )

        tls_config = TLSConfig(
            certificate=cert_config,
            cipher_suites=["TLS_AES_256_GCM_SHA384"],
        )

        assert tls_config.certificate is not None
        assert tls_config.certificate.cert_file == "cert.pem"
        assert tls_config.certificate.validation_mode == CertificateValidationMode.BASIC
        assert tls_config.cipher_suites is not None
        assert "TLS_AES_256_GCM_SHA384" in tls_config.cipher_suites


class TestWebSocketTLSConfig:
    """Test WebSocketTLSConfig basic functionality."""

    def test_ws_tls_config_creation(self) -> None:
        """Test creating WebSocket TLS configuration."""
        ws_tls_config = WebSocketTLSConfig()
        ws_tls_config.tls_config = TLSConfig()
        ws_tls_config.autotls_enabled = True
        ws_tls_config.autotls_domain = "test.local"

        assert ws_tls_config.tls_config is not None
        assert ws_tls_config.autotls_enabled is True
        assert ws_tls_config.autotls_domain == "test.local"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
