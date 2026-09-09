"""WebTransport integration for Noise protocol extensions."""

import hashlib
from typing import Protocol, runtime_checkable


@runtime_checkable
class WebTransportCertificate(Protocol):
    """Protocol for WebTransport certificate handling."""

    def get_certificate_hash(self) -> bytes:
        """
        Get the SHA-256 hash of the certificate.

        Returns:
            bytes: The SHA-256 hash of the certificate

        """
        ...


class WebTransportCertManager:
    """Manager for WebTransport certificate hashes in Noise extensions."""

    def __init__(self) -> None:
        self._cert_hashes: list[bytes] = []

    def add_certificate(self, cert_data: bytes) -> bytes:
        """
        Add a certificate and return its hash.

        Args:
            cert_data: The certificate data

        Returns:
            bytes: The SHA-256 hash of the certificate

        """
        cert_hash = hashlib.sha256(cert_data).digest()
        if cert_hash not in self._cert_hashes:
            self._cert_hashes.append(cert_hash)
        return cert_hash

    def add_certificate_hash(self, cert_hash: bytes) -> None:
        """
        Add a certificate hash directly.

        Args:
            cert_hash: The SHA-256 hash of the certificate

        """
        if cert_hash not in self._cert_hashes:
            self._cert_hashes.append(cert_hash)

    def get_certificate_hashes(self) -> list[bytes]:
        """
        Get all certificate hashes.

        Returns:
            list[bytes]: List of certificate hashes

        """
        return self._cert_hashes.copy()

    def has_certificate_hash(self, cert_hash: bytes) -> bool:
        """
        Check if a certificate hash is present.

        Args:
            cert_hash: The certificate hash to check

        Returns:
            bool: True if the certificate hash is present

        """
        return cert_hash in self._cert_hashes

    def clear_certificates(self) -> None:
        """Clear all certificate hashes."""
        self._cert_hashes.clear()

    def __len__(self) -> int:
        """Get the number of certificate hashes."""
        return len(self._cert_hashes)

    def __bool__(self) -> bool:
        """Check if there are any certificate hashes."""
        return bool(self._cert_hashes)


class WebTransportSupport:
    """Support for WebTransport integration in Noise protocol."""

    def __init__(self) -> None:
        self._cert_manager = WebTransportCertManager()

    @property
    def cert_manager(self) -> WebTransportCertManager:
        """Get the certificate manager."""
        return self._cert_manager

    def add_certificate(self, cert_data: bytes) -> bytes:
        """
        Add a WebTransport certificate.

        Args:
            cert_data: The certificate data

        Returns:
            bytes: The SHA-256 hash of the certificate

        """
        return self._cert_manager.add_certificate(cert_data)

    def get_certificate_hashes(self) -> list[bytes]:
        """
        Get all certificate hashes for extensions.

        Returns:
            list[bytes]: List of certificate hashes

        """
        return self._cert_manager.get_certificate_hashes()

    def has_certificates(self) -> bool:
        """
        Check if any certificates are configured.

        Returns:
            bool: True if certificates are configured

        """
        return bool(self._cert_manager)

    def validate_certificate_hash(self, cert_hash: bytes) -> bool:
        """
        Validate a certificate hash.

        Args:
            cert_hash: The certificate hash to validate

        Returns:
            bool: True if the certificate hash is valid

        """
        # Basic validation: check if it's a valid SHA-256 hash (32 bytes)
        if len(cert_hash) != 32:
            return False

        # Check if it's a known certificate hash
        return self._cert_manager.has_certificate_hash(cert_hash)
