"""
WebRTC certificate utilities.

Generates ECDSA P-256 self-signed certificates for WebRTC DTLS and computes
SHA-256 fingerprints encoded as multihash/multibase for embedding in
``/webrtc-direct/certhash/<encoded>`` multiaddrs.

Spec: https://github.com/libp2p/specs/blob/master/webrtc/webrtc-direct.md
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
from cryptography.x509.oid import NameOID

from .exceptions import WebRTCCertificateError

logger = logging.getLogger(__name__)

# SHA-256 multicodec code per https://github.com/multiformats/multicodec
_SHA256_MULTIHASH_CODE = 0x12
_SHA256_DIGEST_SIZE = 32

# Multibase base64url prefix
_MULTIBASE_BASE64URL_PREFIX = "u"

# Certificate defaults
_CERTIFICATE_VALIDITY_DAYS = 14


class WebRTCCertificate:
    """
    Holds an ECDSA P-256 certificate and its SHA-256 fingerprint for WebRTC.

    Use :meth:`generate` to create a fresh self-signed certificate, or
    :meth:`from_existing` to wrap an already-created certificate/key pair.
    """

    def __init__(
        self,
        certificate: x509.Certificate,
        private_key: ec.EllipticCurvePrivateKey,
    ) -> None:
        self.certificate = certificate
        self.private_key = private_key
        # Pre-compute fingerprint (SHA-256 of DER-encoded certificate)
        der_bytes = certificate.public_bytes(serialization.Encoding.DER)
        self._fingerprint = hashlib.sha256(der_bytes).digest()

    @classmethod
    def generate(
        cls,
        common_name: str = "libp2p-webrtc",
        validity_days: int = _CERTIFICATE_VALIDITY_DAYS,
    ) -> WebRTCCertificate:
        """
        Generate a fresh ECDSA P-256 self-signed certificate.

        The spec requires ECDSA with the P-256 curve for browser compatibility.

        :param common_name: Certificate subject CN.
        :param validity_days: How long the certificate is valid.
        :returns: A new :class:`WebRTCCertificate`.
        :raises WebRTCCertificateError: If certificate generation fails.
        """
        try:
            private_key = ec.generate_private_key(ec.SECP256R1())

            now = datetime.now(timezone.utc)
            subject = issuer = x509.Name(
                [x509.NameAttribute(NameOID.COMMON_NAME, common_name)]
            )
            certificate = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(private_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1))
                .not_valid_after(now + timedelta(days=validity_days))
                .sign(private_key, hashes.SHA256())
            )

            logger.debug("Generated WebRTC ECDSA P-256 certificate")
            return cls(certificate, private_key)

        except Exception as e:
            raise WebRTCCertificateError(
                f"Failed to generate WebRTC certificate: {e}"
            ) from e

    # ------------------------------------------------------------------
    # Fingerprint accessors
    # ------------------------------------------------------------------

    @property
    def fingerprint(self) -> bytes:
        """Raw SHA-256 fingerprint of the DER-encoded certificate."""
        return self._fingerprint

    def fingerprint_to_multihash(self) -> bytes:
        """
        Encode the fingerprint as a multihash (varint code + varint length + digest).

        For SHA-256 both code (0x12) and length (32) fit in a single byte,
        so we avoid a full varint encoder.
        """
        header = struct.pack("BB", _SHA256_MULTIHASH_CODE, _SHA256_DIGEST_SIZE)
        return header + self._fingerprint

    def fingerprint_to_multibase(self) -> str:
        """
        Encode the fingerprint as a multibase base64url string.

        The result can be used directly as the ``certhash`` component in a
        ``/webrtc-direct`` multiaddr.

        Format: ``u`` prefix + base64url(multihash(sha256(DER cert)))
        """
        mh = self.fingerprint_to_multihash()
        encoded = base64.urlsafe_b64encode(mh).rstrip(b"=").decode("ascii")
        return _MULTIBASE_BASE64URL_PREFIX + encoded

    @property
    def fingerprint_hex(self) -> str:
        """Colon-separated hex fingerprint for SDP ``a=fingerprint`` lines."""
        return ":".join(f"{b:02X}" for b in self._fingerprint)

    # ------------------------------------------------------------------
    # DER / PEM accessors
    # ------------------------------------------------------------------

    def certificate_der(self) -> bytes:
        """Certificate in DER encoding."""
        return self.certificate.public_bytes(serialization.Encoding.DER)

    def private_key_der(self) -> bytes:
        """Private key in DER encoding (PKCS8, unencrypted)."""
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )


# ------------------------------------------------------------------
# Standalone helpers for decoding remote fingerprints
# ------------------------------------------------------------------


def fingerprint_from_multibase(encoded: str) -> bytes:
    """
    Decode a multibase-encoded certhash back to raw SHA-256 fingerprint bytes.

    :param encoded: Multibase string (e.g. ``uEi...``).
    :returns: 32-byte SHA-256 digest.
    :raises WebRTCCertificateError: If the encoding is invalid.
    """
    if not encoded.startswith(_MULTIBASE_BASE64URL_PREFIX):
        raise WebRTCCertificateError(
            f"Unsupported multibase prefix: expected '{_MULTIBASE_BASE64URL_PREFIX}', "
            f"got '{encoded[:1]}'"
        )
    b64_part = encoded[1:]
    # Restore padding for base64url
    padding = 4 - (len(b64_part) % 4)
    if padding != 4:
        b64_part += "=" * padding
    try:
        raw = base64.urlsafe_b64decode(b64_part)
    except Exception as e:
        raise WebRTCCertificateError(f"Invalid base64url in certhash: {e}") from e

    if len(raw) < 2:
        raise WebRTCCertificateError("Multihash too short")

    code, length = raw[0], raw[1]
    # Guard: we only handle single-byte varints (code and length < 0x80).
    # SHA-256 (0x12, length 32) fits.  Multi-byte varints would need LEB128.
    if code >= 0x80 or length >= 0x80:
        raise WebRTCCertificateError(
            "Multi-byte varint multihash codes are not supported"
        )
    if code != _SHA256_MULTIHASH_CODE:
        raise WebRTCCertificateError(
            f"Unsupported multihash function code: 0x{code:02x} "
            "(expected 0x12 / SHA-256)"
        )
    if length != _SHA256_DIGEST_SIZE:
        raise WebRTCCertificateError(
            f"Unexpected multihash digest length: {length} "
            f"(expected {_SHA256_DIGEST_SIZE})"
        )
    digest = raw[2:]
    if len(digest) != _SHA256_DIGEST_SIZE:
        raise WebRTCCertificateError(
            f"Digest truncated: got {len(digest)} bytes, expected {_SHA256_DIGEST_SIZE}"
        )
    return digest
