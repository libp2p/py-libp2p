"""
Dual-certificate rotation for WebTransport servers.

At boot: current (valid now) + next (starts when current expires).
Advertised multiaddrs include both certhashes. When current expires,
promote next and mint a new successor.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import threading

from .certificate import WebTransportCertificate
from .exceptions import WebTransportCertificateError

logger = logging.getLogger(__name__)

# Mint current + successor with <14-day windows (W3C ceiling is 14).
_MAX_VALIDITY_DAYS = 13


class WebTransportCertManager:
    """Manages current + next self-signed certificates for WT TLS."""

    def __init__(
        self,
        current: WebTransportCertificate | None = None,
        next_cert: WebTransportCertificate | None = None,
    ) -> None:
        self._lock = threading.Lock()
        if current is None:
            current = WebTransportCertificate.generate()
        if next_cert is None:
            next_cert = self._generate_successor(current)
        self._current = current
        self._next = next_cert
        self._expired: list[WebTransportCertificate] = []

    @staticmethod
    def _generate_successor(
        current: WebTransportCertificate,
    ) -> WebTransportCertificate:
        start = current.not_valid_after
        end = start + timedelta(days=_MAX_VALIDITY_DAYS)
        return WebTransportCertificate.generate(
            not_valid_before=start,
            not_valid_after=end,
            validity_days=_MAX_VALIDITY_DAYS,
        )

    def rotate_if_needed(self, when: datetime | None = None) -> bool:
        """Promote next → current when current is expired. Returns True if rotated."""
        when = when or datetime.now(timezone.utc)
        with self._lock:
            if self._current.is_valid_at(when):
                return False
            logger.info("WebTransport certificate expired; rotating to next")
            self._expired.append(self._current)
            # Keep a short history for Noise extension (recently expired)
            if len(self._expired) > 2:
                self._expired = self._expired[-2:]
            self._current = self._next
            self._next = self._generate_successor(self._current)
            return True

    @property
    def current(self) -> WebTransportCertificate:
        self.rotate_if_needed()
        with self._lock:
            return self._current

    @property
    def next(self) -> WebTransportCertificate:
        self.rotate_if_needed()
        with self._lock:
            return self._next

    def advertised_multihash_bytes(self) -> list[bytes]:
        """Multihash bytes for Noise webtransport_certhashes extension."""
        self.rotate_if_needed()
        with self._lock:
            hashes = [
                self._current.fingerprint_to_multihash(),
                self._next.fingerprint_to_multihash(),
            ]
            for cert in self._expired:
                mh = cert.fingerprint_to_multihash()
                if mh not in hashes:
                    hashes.append(mh)
            return hashes

    def advertised_multibase(self) -> list[str]:
        """Multibase strings for multiaddr ``/certhash/`` components."""
        self.rotate_if_needed()
        with self._lock:
            return [
                self._current.fingerprint_to_multibase(),
                self._next.fingerprint_to_multibase(),
            ]

    def apply_to_quic_configuration(self, config: object) -> None:
        """Set ``certificate`` / ``private_key`` on an aioquic QuicConfiguration."""
        cert = self.current
        try:
            config.certificate = cert.certificate  # type: ignore[attr-defined]
            config.private_key = cert.private_key  # type: ignore[attr-defined]
        except Exception as e:
            raise WebTransportCertificateError(
                f"Failed to apply certificate to QUIC config: {e}"
            ) from e
