"""
WebTransport certificate utilities.

Generates ECDSA P-256 self-signed certificates (≤14 days) and computes
SHA-256 fingerprints as multihash / multibase for ``/certhash/<mh>``.

Leaf generation mirrors go-libp2p ``p2p/transport/webtransport/crypto.go``
(``generateCert``): empty subject, BasicConstraints CA, KeyUsage, and
ExtKeyUsage ServerAuth|ClientAuth so Chromium ``serverCertificateHashes``
accepts the leaf. Default validity is 13 days (strictly under the W3C
≤14-day custom-certificate rule).

Spec: https://github.com/libp2p/specs/blob/master/webtransport/README.md
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import struct

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID

from .exceptions import WebTransportCertificateError

logger = logging.getLogger(__name__)

_SHA256_MULTIHASH_CODE = 0x12
_SHA256_DIGEST_SIZE = 32
_MULTIBASE_BASE64URL_PREFIX = "u"
# W3C WebTransport custom certificate requirement: validity ≤ 14 days.
_MAX_CERTIFICATE_VALIDITY_DAYS = 14
# Prefer strictly under 14 days for Chromium edge cases (matches go-libp2p
# practice of staying inside the window with margin).
_DEFAULT_CERTIFICATE_VALIDITY_DAYS = 13


class WebTransportCertificate:
    """ECDSA P-256 self-signed certificate for WebTransport TLS."""

    def __init__(
        self,
        certificate: x509.Certificate,
        private_key: ec.EllipticCurvePrivateKey,
    ) -> None:
        self.certificate = certificate
        self.private_key = private_key
        der_bytes = certificate.public_bytes(serialization.Encoding.DER)
        self._fingerprint = hashlib.sha256(der_bytes).digest()
        self._der = der_bytes

    @classmethod
    def generate(
        cls,
        common_name: str = "libp2p-webtransport",
        validity_days: int = _DEFAULT_CERTIFICATE_VALIDITY_DAYS,
        not_valid_before: datetime | None = None,
        not_valid_after: datetime | None = None,
    ) -> WebTransportCertificate:
        """
        Generate a fresh ECDSA P-256 self-signed certificate.

        Validity MUST be at most 14 days per the WebTransport / W3C rules.
        Default is 13 days. The leaf uses an empty subject and go-libp2p-aligned
        X.509 extensions so Chromium ``serverCertificateHashes`` accepts it.

        ``common_name`` is retained for API compatibility but is not written
        onto the certificate (Chrome-compatible leaves require an empty
        subject, matching go-libp2p).
        """
        _ = common_name  # API compat; subject must stay empty for Chromium.
        if validity_days > _MAX_CERTIFICATE_VALIDITY_DAYS:
            raise WebTransportCertificateError(
                f"Certificate validity must be ≤{_MAX_CERTIFICATE_VALIDITY_DAYS} days"
            )
        try:
            private_key = ec.generate_private_key(ec.SECP256R1())
            now = datetime.now(timezone.utc)
            start = not_valid_before or (now - timedelta(minutes=1))
            end = not_valid_after or (start + timedelta(days=validity_days))
            if end - start > timedelta(days=_MAX_CERTIFICATE_VALIDITY_DAYS, minutes=2):
                raise WebTransportCertificateError(
                    "Certificate validity window exceeds 14 days"
                )

            # Empty subject/issuer — go-libp2p crypto.go generateCert.
            subject = issuer = x509.Name([])
            certificate = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(private_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(start)
                .not_valid_after(end)
                .add_extension(
                    x509.BasicConstraints(ca=True, path_length=None),
                    critical=True,
                )
                .add_extension(
                    x509.KeyUsage(
                        digital_signature=True,
                        content_commitment=False,
                        key_encipherment=False,
                        data_encipherment=False,
                        key_agreement=False,
                        key_cert_sign=True,
                        crl_sign=False,
                        encipher_only=False,
                        decipher_only=False,
                    ),
                    critical=True,
                )
                .add_extension(
                    x509.ExtendedKeyUsage(
                        [
                            ExtendedKeyUsageOID.SERVER_AUTH,
                            ExtendedKeyUsageOID.CLIENT_AUTH,
                        ]
                    ),
                    critical=False,
                )
                .sign(private_key, hashes.SHA256())
            )
            logger.debug("Generated WebTransport ECDSA P-256 certificate")
            return cls(certificate, private_key)
        except WebTransportCertificateError:
            raise
        except Exception as e:
            raise WebTransportCertificateError(
                f"Failed to generate WebTransport certificate: {e}"
            ) from e

    @property
    def fingerprint(self) -> bytes:
        """Raw SHA-256 fingerprint of the DER-encoded certificate."""
        return self._fingerprint

    @property
    def not_valid_before(self) -> datetime:
        return self.certificate.not_valid_before_utc

    @property
    def not_valid_after(self) -> datetime:
        return self.certificate.not_valid_after_utc

    def is_valid_at(self, when: datetime | None = None) -> bool:
        when = when or datetime.now(timezone.utc)
        return self.not_valid_before <= when <= self.not_valid_after

    def fingerprint_to_multihash(self) -> bytes:
        """Multihash (code + length + digest) for Noise / multiaddr use."""
        header = struct.pack("BB", _SHA256_MULTIHASH_CODE, _SHA256_DIGEST_SIZE)
        return header + self._fingerprint

    def fingerprint_to_multibase(self) -> str:
        """Multibase base64url string for ``/certhash/<encoded>``."""
        mh = self.fingerprint_to_multihash()
        encoded = base64.urlsafe_b64encode(mh).rstrip(b"=").decode("ascii")
        return _MULTIBASE_BASE64URL_PREFIX + encoded

    def certificate_der(self) -> bytes:
        return self._der

    def private_key_der(self) -> bytes:
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )


def fingerprint_from_multibase(encoded: str) -> bytes:
    """Decode multibase certhash to raw SHA-256 digest."""
    if not encoded.startswith(_MULTIBASE_BASE64URL_PREFIX):
        raise WebTransportCertificateError(
            f"Unsupported multibase prefix: expected "
            f"'{_MULTIBASE_BASE64URL_PREFIX}', got '{encoded[:1]}'"
        )
    b64_part = encoded[1:]
    padding = 4 - (len(b64_part) % 4)
    if padding != 4:
        b64_part += "=" * padding
    try:
        raw = base64.urlsafe_b64decode(b64_part)
    except Exception as e:
        raise WebTransportCertificateError(f"Invalid base64url in certhash: {e}") from e
    return _digest_from_multihash(raw)


def multihash_from_multibase(encoded: str) -> bytes:
    """Decode multibase certhash to full multihash bytes."""
    if not encoded.startswith(_MULTIBASE_BASE64URL_PREFIX):
        raise WebTransportCertificateError(
            f"Unsupported multibase prefix: expected "
            f"'{_MULTIBASE_BASE64URL_PREFIX}', got '{encoded[:1]}'"
        )
    b64_part = encoded[1:]
    padding = 4 - (len(b64_part) % 4)
    if padding != 4:
        b64_part += "=" * padding
    try:
        raw = base64.urlsafe_b64decode(b64_part)
    except Exception as e:
        raise WebTransportCertificateError(f"Invalid base64url in certhash: {e}") from e
    _digest_from_multihash(raw)  # validate
    return raw


def multihash_from_der(der: bytes) -> bytes:
    """SHA-256 multihash of a DER-encoded certificate."""
    digest = hashlib.sha256(der).digest()
    return struct.pack("BB", _SHA256_MULTIHASH_CODE, _SHA256_DIGEST_SIZE) + digest


def _digest_from_multihash(raw: bytes) -> bytes:
    if len(raw) < 2:
        raise WebTransportCertificateError("Multihash too short")
    code, length = raw[0], raw[1]
    if code >= 0x80 or length >= 0x80:
        raise WebTransportCertificateError(
            "Multi-byte varint multihash codes are not supported"
        )
    if code != _SHA256_MULTIHASH_CODE:
        raise WebTransportCertificateError(
            f"Unsupported multihash function code: 0x{code:02x} (expected 0x12)"
        )
    if length != _SHA256_DIGEST_SIZE:
        raise WebTransportCertificateError(
            f"Unexpected multihash digest length: {length}"
        )
    digest = raw[2:]
    if len(digest) != _SHA256_DIGEST_SIZE:
        raise WebTransportCertificateError(
            f"Digest truncated: got {len(digest)} bytes, expected {_SHA256_DIGEST_SIZE}"
        )
    return digest
