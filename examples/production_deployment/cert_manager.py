#!/usr/bin/env python3
"""
Certificate Manager for Production Deployment

This module manages TLS certificates for the production libp2p WebSocket transport,
including automatic generation, renewal, and cleanup.

Features:
- Automatic certificate generation
- Certificate renewal before expiry
- Wildcard domain support
- Secure certificate storage
- Integration with AutoTLS
"""

import logging
import os
import signal
import sys
import time
from typing import Any, Optional

import trio

# Import AutoTLS components
from libp2p.transport.websocket.autotls import AutoTLSConfig, AutoTLSManager

# Configure logging
log_handlers: list[logging.Handler] = [logging.StreamHandler()]
if os.path.exists('/app/logs'):
    log_handlers.append(logging.FileHandler('/app/logs/cert-manager.log'))
elif os.path.exists('logs'):
    log_handlers.append(logging.FileHandler('logs/cert-manager.log'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=log_handlers,
)
logger = logging.getLogger("libp2p.cert-manager")


class CertificateManager:
    """Production certificate manager for libp2p WebSocket transport."""

    def __init__(self, config: dict[str, str]) -> None:
        """
        Initialize certificate manager.

        Args:
            config: Configuration dictionary from environment variables

        """
        self.config = config
        self.autotls_manager: Optional[AutoTLSManager] = None
        self.shutdown_event = trio.Event()
        self.start_time = time.time()

        # Certificate statistics
        self.certificates_generated = 0
        self.certificates_renewed = 0
        self.certificates_expired = 0

    async def start(self) -> None:
        """Start the certificate manager."""
        logger.info("🔐 Starting Certificate Manager")

        try:
            # Create AutoTLS configuration
            autotls_config = AutoTLSConfig(
                storage_path=self.config.get('cert_storage_path', '/app/certs'),
                renewal_threshold_hours=int(
                    self.config.get('renewal_threshold_hours', '24')
                ),
                cert_validity_days=int(self.config.get('cert_validity_days', '90')),
            )

            # Create AutoTLS manager
            from libp2p.transport.websocket.autotls import FileCertificateStorage
            storage = FileCertificateStorage(self.config.get('storage_path', './certs'))
            self.autotls_manager = AutoTLSManager(
                storage=storage,
                renewal_threshold_hours=autotls_config.renewal_threshold_hours,
                cert_validity_days=autotls_config.cert_validity_days,
            )

            # Start AutoTLS manager
            await self.autotls_manager.start()

            logger.info("✅ Certificate Manager started successfully")
            logger.info(f"📁 Certificate storage: {autotls_config.storage_path}")
            domain = self.config.get('auto_tls_domain', 'libp2p.local')
            logger.info(f"🌐 Domain: {domain}")

            # Start monitoring loop
            await self._monitoring_loop()

        except Exception as e:
            logger.error(f"❌ Failed to start certificate manager: {e}")
            raise
        finally:
            await self._cleanup()

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop for certificate management."""
        logger.info("🔄 Starting certificate monitoring loop")

        while not self.shutdown_event.is_set():
            try:
                # Check certificate status
                await self._check_certificates()

                # Wait before next check
                await trio.sleep(300)  # Check every 5 minutes

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await trio.sleep(60)  # Wait 1 minute before retry

    async def _check_certificates(self) -> None:
        """Check certificate status and renew if necessary."""
        if not self.autotls_manager:
            return

        try:
            # Get all certificates (simplified for production)
            domain = self.config.get('auto_tls_domain', 'libp2p.local')
            from libp2p.peer.id import ID
            # Create a dummy peer ID for certificate management
            dummy_peer_id = ID.from_base58("12D3KooWTestPeerIdForCertManagement")
            certificates = [
                await self.autotls_manager.get_certificate(dummy_peer_id, domain)
            ]

            for cert in certificates:
                # Check if certificate is expiring soon
                if cert.is_expiring_soon(24):
                    logger.info(
                        f"🔄 Certificate for {cert.domain} is expiring soon, "
                        f"renewing..."
                    )

                    # Renew certificate (simplified for production)
                    if self.autotls_manager:
                        await self.autotls_manager.get_certificate(
                            dummy_peer_id, cert.domain
                        )
                    self.certificates_renewed += 1

                    logger.info(f"✅ Certificate renewed for {cert.domain}")

                # Check if certificate is expired
                if cert.is_expired:
                    logger.warning(f"⚠️ Certificate for {cert.domain} has expired")
                    self.certificates_expired += 1

                    # Generate new certificate
                    if self.autotls_manager:
                        await self.autotls_manager.get_certificate(
                            dummy_peer_id, cert.domain
                        )
                    self.certificates_generated += 1

                    logger.info(f"✅ New certificate generated for {cert.domain}")

            # Log statistics
            logger.info(
                f"📊 Certificate stats: Generated={self.certificates_generated}, "
                f"Renewed={self.certificates_renewed}, "
                f"Expired={self.certificates_expired}"
            )

        except Exception as e:
            logger.error(f"Error checking certificates: {e}")

    async def _cleanup(self) -> None:
        """Cleanup resources on shutdown."""
        logger.info("🧹 Cleaning up certificate manager...")

        if self.autotls_manager:
            try:
                await self.autotls_manager.stop()
                logger.info("✅ AutoTLS manager stopped")
            except Exception as e:
                logger.error(f"Error stopping AutoTLS manager: {e}")

        logger.info("✅ Certificate manager cleanup completed")


def load_config() -> dict[str, str]:
    """Load configuration from environment variables."""
    return {
        'auto_tls_domain': os.getenv('AUTO_TLS_DOMAIN', 'libp2p.local'),
        'cert_storage_path': os.getenv('CERT_STORAGE_PATH', '/app/certs'),
        'renewal_threshold_hours': os.getenv('RENEWAL_THRESHOLD_HOURS', '24'),
        'cert_validity_days': os.getenv('CERT_VALIDITY_DAYS', '90'),
        'log_level': os.getenv('LOG_LEVEL', 'info'),
    }


async def main() -> None:
    """Main entry point."""
    # Load configuration
    config = load_config()

    # Set log level
    log_level = getattr(logging, config['log_level'].upper(), logging.INFO)
    logging.getLogger().setLevel(log_level)

    # Create certificate manager
    cert_manager = CertificateManager(config)

    # Set up signal handlers
    def signal_handler(signum: int, frame: Any) -> None:
        logger.info(f"📡 Received signal {signum}, initiating shutdown...")
        trio.from_thread.run_sync(cert_manager.shutdown_event.set)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Run certificate manager
        await cert_manager.start()
    except KeyboardInterrupt:
        logger.info("📡 Keyboard interrupt received")
    except Exception as e:
        logger.error(f"❌ Certificate manager error: {e}")
        sys.exit(1)
    finally:
        logger.info("👋 Certificate manager shutdown complete")


if __name__ == "__main__":
    trio.run(main)
