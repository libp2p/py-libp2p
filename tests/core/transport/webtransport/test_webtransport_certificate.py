"""Tests for WebTransport certificate generation (Chrome / go-libp2p aligned)."""

from datetime import timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from libp2p.transport.webtransport.cert_manager import WebTransportCertManager
from libp2p.transport.webtransport.certificate import (
    _DEFAULT_CERTIFICATE_VALIDITY_DAYS,
    _MAX_CERTIFICATE_VALIDITY_DAYS,
    WebTransportCertificate,
)
from libp2p.transport.webtransport.exceptions import WebTransportCertificateError


class TestWebTransportCertificateGeneration:
    def test_generate_creates_valid_p256_certificate(self) -> None:
        cert = WebTransportCertificate.generate()
        assert isinstance(cert.certificate, x509.Certificate)
        assert isinstance(cert.private_key, ec.EllipticCurvePrivateKey)
        assert isinstance(cert.private_key.curve, ec.SECP256R1)

    def test_generate_uses_empty_subject(self) -> None:
        cert = WebTransportCertificate.generate(common_name="ignored-for-chrome")
        assert list(cert.certificate.subject) == []
        assert list(cert.certificate.issuer) == []
        cn = cert.certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        assert cn == []

    def test_generate_fingerprint_is_sha256(self) -> None:
        cert = WebTransportCertificate.generate()
        assert len(cert.fingerprint) == 32

    def test_generate_produces_unique_certificates(self) -> None:
        cert1 = WebTransportCertificate.generate()
        cert2 = WebTransportCertificate.generate()
        assert cert1.fingerprint != cert2.fingerprint


class TestChromeCompatibleExtensions:
    def test_basic_constraints_ca_critical(self) -> None:
        cert = WebTransportCertificate.generate()
        ext = cert.certificate.extensions.get_extension_for_class(x509.BasicConstraints)
        assert ext.critical is True
        assert ext.value.ca is True

    def test_key_usage_digital_signature_and_cert_sign(self) -> None:
        cert = WebTransportCertificate.generate()
        ext = cert.certificate.extensions.get_extension_for_class(x509.KeyUsage)
        assert ext.critical is True
        assert ext.value.digital_signature is True
        assert ext.value.key_cert_sign is True

    def test_extended_key_usage_server_and_client_auth(self) -> None:
        cert = WebTransportCertificate.generate()
        ext = cert.certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        assert ext.critical is False
        assert ExtendedKeyUsageOID.SERVER_AUTH in ext.value
        assert ExtendedKeyUsageOID.CLIENT_AUTH in ext.value


class TestValidityWindow:
    def test_default_validity_under_14_days(self) -> None:
        cert = WebTransportCertificate.generate()
        window = cert.not_valid_after - cert.not_valid_before
        assert window < timedelta(days=_MAX_CERTIFICATE_VALIDITY_DAYS)
        # Default mint is 13 days; allow 1 minute skew from not_valid_before offset.
        assert window <= timedelta(days=_DEFAULT_CERTIFICATE_VALIDITY_DAYS, minutes=2)
        assert window >= timedelta(days=_DEFAULT_CERTIFICATE_VALIDITY_DAYS) - timedelta(
            minutes=2
        )

    def test_explicit_14_day_validity_allowed(self) -> None:
        cert = WebTransportCertificate.generate(validity_days=14)
        window = cert.not_valid_after - cert.not_valid_before
        assert window <= timedelta(days=14, minutes=2)

    def test_validity_over_14_days_rejected(self) -> None:
        with pytest.raises(WebTransportCertificateError, match="≤14"):
            WebTransportCertificate.generate(validity_days=15)

    def test_explicit_window_over_14_days_rejected(self) -> None:
        from datetime import datetime, timezone

        start = datetime.now(timezone.utc)
        end = start + timedelta(days=15)
        with pytest.raises(WebTransportCertificateError, match="exceeds 14"):
            WebTransportCertificate.generate(
                not_valid_before=start,
                not_valid_after=end,
                validity_days=13,
            )


class TestCertManagerWindows:
    def test_current_and_next_under_14_days(self) -> None:
        manager = WebTransportCertManager()
        for cert in (manager.current, manager.next):
            window = cert.not_valid_after - cert.not_valid_before
            assert window < timedelta(days=14)
            assert window <= timedelta(days=13, minutes=2)

    def test_advertises_two_certhashes(self) -> None:
        manager = WebTransportCertManager()
        hashes = manager.advertised_multibase()
        assert len(hashes) == 2
        assert hashes[0] != hashes[1]
        assert all(h.startswith("u") for h in hashes)
