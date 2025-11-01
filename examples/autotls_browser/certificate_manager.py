"""
Certificate Manager for AutoTLS

This module provides advanced certificate management capabilities
for AutoTLS functionality, including certificate generation,
validation, and lifecycle management.
"""

import asyncio
from datetime import datetime, timedelta
import logging
from pathlib import Path
import ssl
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from libp2p.peer.id import ID

logger = logging.getLogger("libp2p.autotls.certificate_manager")


class CertificateManager:
    """Advanced certificate manager for AutoTLS."""

    def __init__(
        self,
        storage_path: str = "autotls-certs",
        key_size: int = 2048,
        cert_validity_days: int = 90,
        renewal_threshold_hours: int = 24,
    ) -> None:
        """
        Initialize certificate manager.

        Args:
            storage_path: Path for certificate storage
            key_size: RSA key size in bits
            cert_validity_days: Certificate validity period in days
            renewal_threshold_hours: Hours before expiry to renew

        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.key_size = key_size
        self.cert_validity_days = cert_validity_days
        self.renewal_threshold_hours = renewal_threshold_hours

        self._certificates: dict[tuple[ID, str], dict[Any, Any]] = {}
        self._renewal_tasks: dict[tuple[ID, str], asyncio.Task[Any]] = {}

    async def get_certificate(
        self,
        peer_id: ID,
        domain: str,
        force_renew: bool = False,
    ) -> tuple[str, str]:
        """
        Get or generate certificate for peer ID and domain.

        Args:
            peer_id: Peer ID
            domain: Certificate domain
            force_renew: Force certificate renewal

        Returns:
            Tuple of (cert_pem, key_pem)

        """
        key = (peer_id, domain)

        # Check if we have a valid cached certificate
        if not force_renew and key in self._certificates:
            cert_data = self._certificates[key]
            if not self._is_certificate_expired(cert_data):
                return cert_data["cert_pem"], cert_data["key_pem"]

        # Try to load from storage
        if not force_renew:
            loaded_cert = await self._load_certificate_from_storage(peer_id, domain)
            if loaded_cert is not None and not self._is_certificate_expired(
                loaded_cert
            ):
                self._certificates[key] = loaded_cert
                await self._schedule_renewal(peer_id, domain, loaded_cert)
                return loaded_cert["cert_pem"], loaded_cert["key_pem"]

        # Generate new certificate
        logger.info(f"Generating new certificate for {peer_id} on {domain}")
        cert_data = await self._generate_certificate(peer_id, domain)

        # Store certificate
        await self._store_certificate_to_storage(peer_id, domain, cert_data)
        self._certificates[key] = cert_data

        # Schedule renewal
        await self._schedule_renewal(peer_id, domain, cert_data)

        return cert_data["cert_pem"], cert_data["key_pem"]

    async def _generate_certificate(
        self,
        peer_id: ID,
        domain: str,
    ) -> dict[Any, Any]:
        """Generate a new TLS certificate."""
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=self.key_size,
        )

        # Generate certificate
        now = datetime.utcnow()
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
                        x509.DNSName("localhost"),  # Always include localhost
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

        return {
            "cert_pem": cert_pem,
            "key_pem": key_pem,
            "peer_id": peer_id.to_base58(),
            "domain": domain,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

    def _is_certificate_expired(self, cert_data: dict[Any, Any]) -> bool:
        """Check if certificate is expired."""
        expires_at = datetime.fromisoformat(cert_data["expires_at"])
        return datetime.utcnow() >= expires_at

    def _is_certificate_expiring_soon(self, cert_data: dict[Any, Any]) -> bool:
        """Check if certificate expires within threshold."""
        expires_at = datetime.fromisoformat(cert_data["expires_at"])
        threshold = datetime.utcnow() + timedelta(hours=self.renewal_threshold_hours)
        return expires_at <= threshold

    async def _schedule_renewal(
        self,
        peer_id: ID,
        domain: str,
        cert_data: dict[Any, Any],
    ) -> None:
        """Schedule certificate renewal."""
        key = (peer_id, domain)

        # Cancel existing renewal task
        if key in self._renewal_tasks:
            self._renewal_tasks[key].cancel()

        # Calculate renewal time
        expires_at = datetime.fromisoformat(cert_data["expires_at"])
        renewal_time = expires_at - timedelta(hours=self.renewal_threshold_hours)
        delay = (renewal_time - datetime.utcnow()).total_seconds()

        if delay <= 0:
            # Certificate needs immediate renewal
            delay = 1

        logger.info(
            f"Scheduling certificate renewal for {peer_id} in {delay:.0f} seconds"
        )

        async def renew_certificate() -> None:
            try:
                await asyncio.sleep(delay)

                logger.info(f"Renewing certificate for {peer_id} on {domain}")
                new_cert_data = await self.get_certificate(
                    peer_id, domain, force_renew=True
                )

                # Update cached certificate
                self._certificates[key] = new_cert_data  # type: ignore

            except asyncio.CancelledError:
                logger.debug(f"Certificate renewal cancelled for {peer_id}")
            except Exception as e:
                logger.error(f"Certificate renewal failed for {peer_id}: {e}")

        self._renewal_tasks[key] = asyncio.create_task(renew_certificate())

    def _get_cert_path(self, peer_id: ID, domain: str) -> Path:
        """Get certificate file path."""
        safe_domain = domain.replace(".", "_").replace("*", "wildcard")
        return self.storage_path / f"{peer_id.to_base58()}_{safe_domain}.json"

    async def _load_certificate_from_storage(
        self,
        peer_id: ID,
        domain: str,
    ) -> dict[Any, Any] | None:
        """Load certificate from storage."""
        cert_path = self._get_cert_path(peer_id, domain)

        if not cert_path.exists():
            return None

        try:
            import json

            with open(cert_path) as f:
                return json.load(f)
        except (KeyError, ValueError, FileNotFoundError):
            return None

    async def _store_certificate_to_storage(
        self,
        peer_id: ID,
        domain: str,
        cert_data: dict[Any, Any],
    ) -> None:
        """Store certificate to storage."""
        cert_path = self._get_cert_path(peer_id, domain)

        import json

        with open(cert_path, "w") as f:
            json.dump(cert_data, f, indent=2)

    def get_ssl_context(
        self,
        peer_id: ID,
        domain: str,
    ) -> ssl.SSLContext | None:
        """Get SSL context for peer ID and domain."""
        key = (peer_id, domain)
        if key not in self._certificates:
            return None

        cert_data = self._certificates[key]
        if self._is_certificate_expired(cert_data):
            return None

        # Create SSL context
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)

        # Create temporary files for certificate and key
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pem", delete=False
        ) as cert_file:
            cert_file.write(cert_data["cert_pem"])
            cert_path = cert_file.name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".pem", delete=False
        ) as key_file:
            key_file.write(cert_data["key_pem"])
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

    async def cleanup_expired_certificates(self) -> None:
        """Clean up expired certificates."""
        expired_keys = []

        for key, cert_data in self._certificates.items():
            if self._is_certificate_expired(cert_data):
                expired_keys.append(key)

        for key in expired_keys:
            peer_id, domain = key
            cert_path = self._get_cert_path(peer_id, domain)
            if cert_path.exists():
                cert_path.unlink()
            del self._certificates[key]

            # Cancel renewal task
            if key in self._renewal_tasks:
                self._renewal_tasks[key].cancel()
                del self._renewal_tasks[key]

        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired certificates")

    async def get_certificate_info(
        self,
        peer_id: ID,
        domain: str,
    ) -> dict[Any, Any] | None:
        """Get certificate information."""
        key = (peer_id, domain)
        if key not in self._certificates:
            return None

        cert_data = self._certificates[key]
        return {
            "peer_id": cert_data["peer_id"],
            "domain": cert_data["domain"],
            "created_at": cert_data["created_at"],
            "expires_at": cert_data["expires_at"],
            "is_expired": self._is_certificate_expired(cert_data),
            "is_expiring_soon": self._is_certificate_expiring_soon(cert_data),
        }

    async def list_certificates(self) -> list[dict[Any, Any]]:
        """List all certificates."""
        certificates = []

        for key, cert_data in self._certificates.items():
            peer_id, domain = key
            info = await self.get_certificate_info(peer_id, domain)
            if info:
                certificates.append(info)

        return certificates

    async def revoke_certificate(
        self,
        peer_id: ID,
        domain: str,
    ) -> None:
        """Revoke a certificate."""
        key = (peer_id, domain)

        # Remove from cache
        if key in self._certificates:
            del self._certificates[key]

        # Cancel renewal task
        if key in self._renewal_tasks:
            self._renewal_tasks[key].cancel()
            del self._renewal_tasks[key]

        # Remove from storage
        cert_path = self._get_cert_path(peer_id, domain)
        if cert_path.exists():
            cert_path.unlink()

        logger.info(f"Revoked certificate for {peer_id} on {domain}")

    async def shutdown(self) -> None:
        """Shutdown certificate manager."""
        # Cancel all renewal tasks
        for task in self._renewal_tasks.values():
            if not task.done():
                task.cancel()

        # Wait for tasks to complete
        if self._renewal_tasks:
            await asyncio.gather(*self._renewal_tasks.values(), return_exceptions=True)

        logger.info("Certificate manager shutdown complete")
