"""
AutoTLS implementation for WebSocket transport.

This module provides automatic TLS certificate management for libp2p WebSocket
transport, enabling seamless browser-to-Python connections without manual
certificate setup.

Based on patterns from JavaScript and Go libp2p implementations.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import ssl
import tempfile
from typing import Protocol

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from libp2p.peer.id import ID

logger = logging.getLogger("libp2p.websocket.autotls")


class TLSCertificate:
    """Represents a TLS certificate with metadata."""

    def __init__(
        self,
        cert_pem: str,
        key_pem: str,
        peer_id: ID,
        domain: str,
        expires_at: datetime,
        created_at: datetime | None = None,
    ) -> None:
        """
        Initialize TLS certificate.

        Args:
            cert_pem: PEM-encoded certificate
            key_pem: PEM-encoded private key
            peer_id: Associated peer ID
            domain: Certificate domain
            expires_at: Certificate expiration time
            created_at: Certificate creation time (defaults to now)

        """
        self.cert_pem = cert_pem
        self.key_pem = key_pem
        self.peer_id = peer_id
        self.domain = domain
        self.expires_at = expires_at
        self.created_at = created_at or datetime.now(timezone.utc)

    @property
    def is_expired(self) -> bool:
        """Check if certificate is expired."""
        return datetime.now(timezone.utc) >= self.expires_at

    def is_expiring_soon(self, threshold_hours: int = 24) -> bool:
        """Check if certificate expires within threshold."""
        threshold = datetime.now(timezone.utc) + timedelta(hours=threshold_hours)
        return self.expires_at <= threshold

    def to_ssl_context(self) -> ssl.SSLContext:
        """Convert certificate to SSL context."""
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)

        # Create temporary files for certificate and key
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pem", delete=False
        ) as cert_file:
            cert_file.write(self.cert_pem)
            cert_path = cert_file.name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pem", delete=False
        ) as key_file:
            key_file.write(self.key_pem)
            key_path = key_file.name

        try:
            context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        finally:
            # Clean up temporary files
            import os

            try:
                os.unlink(cert_path)
                os.unlink(key_path)
            except OSError:
                pass

        return context


class CertificateStorage(Protocol):
    """Protocol for certificate storage backends."""

    async def store_certificate(self, cert: TLSCertificate) -> None:
        """Store certificate."""
        ...

    async def load_certificate(self, peer_id: ID, domain: str) -> TLSCertificate | None:
        """Load certificate for peer ID and domain."""
        ...

    async def delete_certificate(self, peer_id: ID, domain: str) -> None:
        """Delete certificate."""
        ...


class FileCertificateStorage:
    """File-based certificate storage implementation."""

    def __init__(self, storage_path: str | Path) -> None:
        """
        Initialize file storage.

        Args:
            storage_path: Directory to store certificates

        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _get_cert_path(self, peer_id: ID, domain: str) -> Path:
        """Get certificate file path."""
        safe_domain = domain.replace(".", "_").replace("*", "wildcard")
        return self.storage_path / f"{peer_id.to_base58()}_{safe_domain}.pem"

    async def store_certificate(self, cert: TLSCertificate) -> None:
        """Store certificate to file."""
        cert_path = self._get_cert_path(cert.peer_id, cert.domain)

        cert_data = {
            "cert_pem": cert.cert_pem,
            "key_pem": cert.key_pem,
            "peer_id": cert.peer_id.to_base58(),
            "domain": cert.domain,
            "expires_at": cert.expires_at.isoformat(),
            "created_at": cert.created_at.isoformat(),
        }

        import json

        with open(cert_path, "w") as f:
            json.dump(cert_data, f, indent=2)

    async def load_certificate(self, peer_id: ID, domain: str) -> TLSCertificate | None:
        """Load certificate from file."""
        cert_path = self._get_cert_path(peer_id, domain)

        if not cert_path.exists():
            return None

        try:
            import json

            with open(cert_path) as f:
                cert_data = json.load(f)

            return TLSCertificate(
                cert_pem=cert_data["cert_pem"],
                key_pem=cert_data["key_pem"],
                peer_id=ID.from_base58(cert_data["peer_id"]),
                domain=cert_data["domain"],
                expires_at=datetime.fromisoformat(cert_data["expires_at"]),
                created_at=datetime.fromisoformat(cert_data["created_at"]),
            )
        except (KeyError, ValueError, FileNotFoundError):
            return None

    async def delete_certificate(self, peer_id: ID, domain: str) -> None:
        """Delete certificate file."""
        cert_path = self._get_cert_path(peer_id, domain)
        if cert_path.exists():
            cert_path.unlink()


class AutoTLSManager:
    """
    Automatic TLS certificate manager for WebSocket transport.

    Manages certificate lifecycle including generation, storage, renewal,
    and integration with WebSocket transport.
    """

    def __init__(
        self,
        storage: CertificateStorage | None = None,
        renewal_threshold_hours: int = 24,
        cert_validity_days: int = 90,
        on_certificate_provision: Callable[[TLSCertificate], None] | None = None,
        on_certificate_renew: Callable[[TLSCertificate], None] | None = None,
    ) -> None:
        """
        Initialize AutoTLS manager.

        Args:
            storage: Certificate storage backend
            renewal_threshold_hours: Hours before expiry to renew certificate
            cert_validity_days: Certificate validity period in days
            on_certificate_provision: Callback when certificate is provisioned
            on_certificate_renew: Callback when certificate is renewed

        """
        self.storage = storage or FileCertificateStorage("autotls-certs")
        self.renewal_threshold_hours = renewal_threshold_hours
        self.cert_validity_days = cert_validity_days
        self.on_certificate_provision = on_certificate_provision
        self.on_certificate_renew = on_certificate_renew

        self._active_certificates: dict[tuple[ID, str], TLSCertificate] = {}
        self._renewal_tasks: dict[tuple[ID, str], asyncio.Task[None]] = {}
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """Start the AutoTLS manager."""
        logger.info("Starting AutoTLS manager")
        # Manager is ready to handle certificate requests
        pass

    async def stop(self) -> None:
        """Stop the AutoTLS manager."""
        logger.info("Stopping AutoTLS manager")
        self._shutdown_event.set()

        # Cancel all renewal tasks
        for task in self._renewal_tasks.values():
            if not task.done():
                task.cancel()

        # Wait for tasks to complete
        if self._renewal_tasks:
            await asyncio.gather(*self._renewal_tasks.values(), return_exceptions=True)

    async def get_certificate(
        self,
        peer_id: ID,
        domain: str,
        force_renew: bool = False,
    ) -> TLSCertificate:
        """
        Get or generate certificate for peer ID and domain.

        Args:
            peer_id: Peer ID
            domain: Certificate domain
            force_renew: Force certificate renewal

        Returns:
            TLS certificate

        """
        key = (peer_id, domain)

        # Check if we have a valid cached certificate
        if not force_renew and key in self._active_certificates:
            cert = self._active_certificates[key]
            if not cert.is_expired and not cert.is_expiring_soon(
                self.renewal_threshold_hours
            ):
                return cert

        # Try to load from storage
        if not force_renew:
            stored_cert = await self.storage.load_certificate(peer_id, domain)
            if stored_cert and not stored_cert.is_expired:
                self._active_certificates[key] = stored_cert
                await self._schedule_renewal(peer_id, domain, stored_cert)
                return stored_cert

        # Generate new certificate
        logger.info(f"Generating new certificate for {peer_id} on {domain}")
        cert = await self._generate_certificate(peer_id, domain)

        # Store certificate
        await self.storage.store_certificate(cert)
        self._active_certificates[key] = cert

        # Schedule renewal
        await self._schedule_renewal(peer_id, domain, cert)

        # Notify provision
        if self.on_certificate_provision:
            self.on_certificate_provision(cert)

        return cert

    async def _generate_certificate(self, peer_id: ID, domain: str) -> TLSCertificate:
        """Generate a new TLS certificate."""
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Generate certificate
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=self.cert_validity_days)

        # Create certificate
        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),  # type: ignore
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "CA"),  # type: ignore
                x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),  # type: ignore
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "libp2p"),  # type: ignore
                x509.NameAttribute(NameOID.COMMON_NAME, domain),  # type: ignore
            ]
        )

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(expires_at)
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName(domain),
                        x509.DNSName(f"*.{domain}"),  # Wildcard for subdomains
                    ]
                ),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )

        # Serialize to PEM
        cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()

        return TLSCertificate(
            cert_pem=cert_pem,
            key_pem=key_pem,
            peer_id=peer_id,
            domain=domain,
            expires_at=expires_at,
        )

    async def _schedule_renewal(
        self,
        peer_id: ID,
        domain: str,
        cert: TLSCertificate,
    ) -> None:
        """Schedule certificate renewal."""
        key = (peer_id, domain)

        # Cancel existing renewal task
        if key in self._renewal_tasks:
            self._renewal_tasks[key].cancel()

        # Calculate renewal time
        renewal_time = cert.expires_at - timedelta(hours=self.renewal_threshold_hours)
        delay = (renewal_time - datetime.now(timezone.utc)).total_seconds()

        if delay <= 0:
            # Certificate needs immediate renewal
            delay = 1

        logger.info(
            f"Scheduling certificate renewal for {peer_id} in {delay:.0f} seconds"
        )

        async def renew_certificate() -> None:
            try:
                await asyncio.sleep(delay)

                if self._shutdown_event.is_set():
                    return

                logger.info(f"Renewing certificate for {peer_id} on {domain}")
                new_cert = await self.get_certificate(peer_id, domain, force_renew=True)

                # Notify renewal
                if self.on_certificate_renew:
                    self.on_certificate_renew(new_cert)

            except asyncio.CancelledError:
                logger.debug(f"Certificate renewal cancelled for {peer_id}")
            except Exception as e:
                logger.error(f"Certificate renewal failed for {peer_id}: {e}")

        self._renewal_tasks[key] = asyncio.create_task(renew_certificate())

    def get_ssl_context(self, peer_id: ID | None, domain: str) -> ssl.SSLContext | None:
        """Get SSL context for peer ID and domain."""
        # If peer_id is None, try to find any valid certificate for the domain
        if peer_id is None:
            for (pid, d), cert in self._active_certificates.items():
                if d == domain and not cert.is_expired:
                    return cert.to_ssl_context()
            return None

        key = (peer_id, domain)
        if key not in self._active_certificates:
            return None

        cert = self._active_certificates[key]
        if cert.is_expired:
            return None

        return cert.to_ssl_context()


class AutoTLSConfig:
    """Configuration for AutoTLS functionality."""

    def __init__(
        self,
        enabled: bool = True,
        storage_path: str | Path = "autotls-certs",
        renewal_threshold_hours: int = 24,
        cert_validity_days: int = 90,
        default_domain: str = "libp2p.local",
        wildcard_domain: bool = True,
    ) -> None:
        """
        Initialize AutoTLS configuration.

        Args:
            enabled: Enable AutoTLS functionality
            storage_path: Path for certificate storage
            renewal_threshold_hours: Hours before expiry to renew
            cert_validity_days: Certificate validity period
            default_domain: Default domain for certificates
            wildcard_domain: Enable wildcard domain support

        """
        self.enabled = enabled
        self.storage_path = Path(storage_path)
        self.renewal_threshold_hours = renewal_threshold_hours
        self.cert_validity_days = cert_validity_days
        self.default_domain = default_domain
        self.wildcard_domain = wildcard_domain

    def validate(self) -> None:
        """Validate configuration."""
        if self.renewal_threshold_hours <= 0:
            raise ValueError("renewal_threshold_hours must be positive")
        if self.cert_validity_days <= 0:
            raise ValueError("cert_validity_days must be positive")
        if not self.default_domain:
            raise ValueError("default_domain cannot be empty")


# Global AutoTLS manager instance
_autotls_manager: AutoTLSManager | None = None


def get_autotls_manager() -> AutoTLSManager | None:
    """Get the global AutoTLS manager instance."""
    return _autotls_manager


def set_autotls_manager(manager: AutoTLSManager) -> None:
    """Set the global AutoTLS manager instance."""
    global _autotls_manager
    _autotls_manager = manager


async def initialize_autotls(config: AutoTLSConfig) -> AutoTLSManager:
    """
    Initialize AutoTLS with configuration.

    Args:
        config: AutoTLS configuration

    Returns:
        Initialized AutoTLS manager

    """
    config.validate()

    storage = FileCertificateStorage(config.storage_path)
    manager = AutoTLSManager(
        storage=storage,
        renewal_threshold_hours=config.renewal_threshold_hours,
        cert_validity_days=config.cert_validity_days,
    )

    await manager.start()
    set_autotls_manager(manager)

    return manager
