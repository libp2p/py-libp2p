"""
Tests for WebRTC certificate generation and fingerprint encoding.
"""
# pyrefly: ignore

import base64
import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509 import Certificate

from libp2p.transport.webrtc.certificate import (
    WebRTCCertificate,
    fingerprint_from_multibase,
)
from libp2p.transport.webrtc.exceptions import WebRTCCertificateError


class TestWebRTCCertificateGeneration:
    """Test certificate generation."""

    def test_generate_creates_valid_certificate(self):
        cert = WebRTCCertificate.generate()
        assert isinstance(cert.certificate, Certificate)
        assert isinstance(cert.private_key, ec.EllipticCurvePrivateKey)

    def test_generate_uses_p256_curve(self):
        cert = WebRTCCertificate.generate()
        # The private key should be on the SECP256R1 (P-256) curve
        assert isinstance(cert.private_key.curve, ec.SECP256R1)

    def test_generate_produces_unique_certificates(self):
        cert1 = WebRTCCertificate.generate()
        cert2 = WebRTCCertificate.generate()
        assert cert1.fingerprint != cert2.fingerprint

    def test_generate_custom_common_name(self):
        cert = WebRTCCertificate.generate(common_name="test-node")
        # Verify the CN is set correctly by checking subject attributes
        from cryptography.x509.oid import NameOID

        cn_attrs = cert.certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        assert len(cn_attrs) == 1
        assert cn_attrs[0].value == "test-node"


class TestFingerprint:
    """Test fingerprint computation and encoding."""

    def test_fingerprint_is_sha256(self):
        cert = WebRTCCertificate.generate()
        der = cert.certificate_der()
        expected = hashlib.sha256(der).digest()
        assert cert.fingerprint == expected

    def test_fingerprint_is_32_bytes(self):
        cert = WebRTCCertificate.generate()
        assert len(cert.fingerprint) == 32

    def test_fingerprint_hex_format(self):
        cert = WebRTCCertificate.generate()
        hex_fp = cert.fingerprint_hex
        # Should be colon-separated hex pairs: "AB:CD:EF:..."
        parts = hex_fp.split(":")
        assert len(parts) == 32
        for part in parts:
            assert len(part) == 2
            int(part, 16)  # Should not raise

    def test_fingerprint_to_multihash(self):
        cert = WebRTCCertificate.generate()
        mh = cert.fingerprint_to_multihash()
        # Multihash: code(1 byte) + length(1 byte) + digest(32 bytes)
        assert len(mh) == 34
        assert mh[0] == 0x12  # SHA-256 code
        assert mh[1] == 32  # digest length
        assert mh[2:] == cert.fingerprint

    def test_fingerprint_to_multibase(self):
        cert = WebRTCCertificate.generate()
        mb = cert.fingerprint_to_multibase()
        # Should start with 'u' (base64url prefix)
        assert mb.startswith("u")
        # Should be decodable
        b64_part = mb[1:]
        # Add padding
        padding = 4 - (len(b64_part) % 4)
        if padding != 4:
            b64_part += "=" * padding
        raw = base64.urlsafe_b64decode(b64_part)
        # Should be a valid multihash
        assert raw[0] == 0x12
        assert raw[1] == 32
        assert raw[2:] == cert.fingerprint


class TestFingerprintRoundTrip:
    """Test multibase encode/decode round-trip."""

    def test_round_trip(self):
        cert = WebRTCCertificate.generate()
        encoded = cert.fingerprint_to_multibase()
        decoded = fingerprint_from_multibase(encoded)
        assert decoded == cert.fingerprint

    def test_round_trip_multiple_certs(self):
        for _ in range(5):
            cert = WebRTCCertificate.generate()
            encoded = cert.fingerprint_to_multibase()
            decoded = fingerprint_from_multibase(encoded)
            assert decoded == cert.fingerprint


class TestFingerprintFromMultibase:
    """Test decoding multibase-encoded fingerprints."""

    def test_invalid_prefix(self):
        with pytest.raises(
            WebRTCCertificateError, match="Unsupported multibase prefix"
        ):
            fingerprint_from_multibase("zInvalidBase58")

    def test_invalid_base64(self):
        with pytest.raises(WebRTCCertificateError):
            fingerprint_from_multibase("u!!!invalid!!!")

    def test_too_short(self):
        # Just the prefix + 1 byte (too short for multihash)
        encoded = "u" + base64.urlsafe_b64encode(b"\x12").rstrip(b"=").decode()
        with pytest.raises(WebRTCCertificateError, match="too short"):
            fingerprint_from_multibase(encoded)

    def test_wrong_hash_function(self):
        # Use code 0x11 (SHA-1) instead of 0x12 (SHA-256)
        fake_mh = bytes([0x11, 32]) + b"\x00" * 32
        encoded = "u" + base64.urlsafe_b64encode(fake_mh).rstrip(b"=").decode()
        with pytest.raises(WebRTCCertificateError, match="Unsupported multihash"):
            fingerprint_from_multibase(encoded)

    def test_wrong_digest_length(self):
        fake_mh = bytes([0x12, 16]) + b"\x00" * 16  # Wrong length
        encoded = "u" + base64.urlsafe_b64encode(fake_mh).rstrip(b"=").decode()
        with pytest.raises(WebRTCCertificateError, match="digest length"):
            fingerprint_from_multibase(encoded)

    def test_truncated_digest(self):
        fake_mh = bytes([0x12, 32]) + b"\x00" * 20  # Only 20 bytes of 32
        encoded = "u" + base64.urlsafe_b64encode(fake_mh).rstrip(b"=").decode()
        with pytest.raises(WebRTCCertificateError, match="truncated"):
            fingerprint_from_multibase(encoded)


class TestDERPEM:
    """Test DER/PEM accessors."""

    def test_certificate_der(self):
        cert = WebRTCCertificate.generate()
        der = cert.certificate_der()
        assert isinstance(der, bytes)
        assert len(der) > 100  # Reasonable minimum

    def test_private_key_der(self):
        cert = WebRTCCertificate.generate()
        key_der = cert.private_key_der()
        assert isinstance(key_der, bytes)
        assert len(key_der) > 50
