"""
Advanced TLS configuration for WebSocket transport.

This module provides comprehensive TLS configuration options including
SNI support, certificate validation, and advanced TLS features.
"""

from dataclasses import dataclass, field
from enum import Enum
import ssl

from libp2p.peer.id import ID


class TLSVersion(Enum):
    """TLS version enumeration."""

    TLS_1_0 = "TLSv1"
    TLS_1_1 = "TLSv1.1"
    TLS_1_2 = "TLSv1.2"
    TLS_1_3 = "TLSv1.3"


class CertificateValidationMode(Enum):
    """Certificate validation mode."""

    NONE = "none"  # No validation
    BASIC = "basic"  # Basic certificate validation
    STRICT = "strict"  # Strict certificate validation
    VERIFY_PEER = "verify_peer"  # Verify peer certificates


@dataclass
class SNIConfig:
    """Server Name Indication (SNI) configuration."""

    enabled: bool = True
    default_domain: str = "localhost"
    domain_mapping: dict[str, str] = field(default_factory=dict)
    wildcard_support: bool = True

    def get_domain_for_sni(self, sni_name: str | None) -> str:
        """
        Get domain for SNI name.

        Args:
            sni_name: SNI name from client

        Returns:
            Domain to use for certificate lookup

        """
        if not sni_name:
            return self.default_domain

        # Check direct mapping
        if sni_name in self.domain_mapping:
            return self.domain_mapping[sni_name]

        # Check wildcard mapping
        if self.wildcard_support:
            for pattern, domain in self.domain_mapping.items():
                if pattern.startswith("*.") and sni_name.endswith(pattern[1:]):
                    return domain

        return sni_name


@dataclass
class CertificateConfig:
    """Certificate configuration."""

    # Certificate sources
    cert_file: str | None = None
    key_file: str | None = None
    cert_data: str | None = None
    key_data: str | None = None

    # Certificate validation
    validation_mode: CertificateValidationMode = CertificateValidationMode.BASIC
    verify_peer: bool = True
    verify_hostname: bool = True

    # Certificate chain
    ca_file: str | None = None
    ca_data: str | None = None
    ca_path: str | None = None

    # Client certificates
    client_cert_file: str | None = None
    client_key_file: str | None = None
    client_cert_data: str | None = None
    client_key_data: str | None = None

    def validate(self) -> None:
        """Validate certificate configuration."""
        # Check that we have either file or data sources
        if not any([self.cert_file, self.cert_data]):
            raise ValueError("Either cert_file or cert_data must be provided")

        if not any([self.key_file, self.key_data]):
            raise ValueError("Either key_file or key_data must be provided")

        # Validate file paths if provided
        if self.cert_file and not Path(self.cert_file).exists():
            raise ValueError(f"Certificate file not found: {self.cert_file}")

        if self.key_file and not Path(self.key_file).exists():
            raise ValueError(f"Key file not found: {self.key_file}")

        if self.ca_file and not Path(self.ca_file).exists():
            raise ValueError(f"CA file not found: {self.ca_file}")


@dataclass
class TLSConfig:
    """Comprehensive TLS configuration."""

    # Basic TLS settings
    enabled: bool = True
    min_version: TLSVersion = TLSVersion.TLS_1_2
    max_version: TLSVersion = TLSVersion.TLS_1_3

    # Certificate configuration
    certificate: CertificateConfig | None = None

    # SNI configuration
    sni: SNIConfig | None = None

    # Cipher suites
    cipher_suites: list[str] | None = None
    prefer_server_ciphers: bool = True

    # Session management
    session_cache_size: int = 128
    session_timeout: int = 300  # seconds

    # Security settings
    insecure_skip_verify: bool = False
    allow_insecure_ciphers: bool = False

    # ALPN (Application-Layer Protocol Negotiation)
    alpn_protocols: list[str] = field(default_factory=lambda: ["h2", "http/1.1"])

    # Client settings
    client_auth: bool = False
    client_ca_file: str | None = None

    # Performance settings
    renegotiation: bool = False
    compression: bool = False

    def validate(self) -> None:
        """Validate TLS configuration."""
        if self.min_version.value > self.max_version.value:
            raise ValueError("min_version cannot be greater than max_version")

        if self.certificate:
            self.certificate.validate()

        if self.session_cache_size < 0:
            raise ValueError("session_cache_size must be non-negative")

        if self.session_timeout < 0:
            raise ValueError("session_timeout must be non-negative")

    def to_ssl_context(
        self, purpose: ssl.Purpose = ssl.Purpose.SERVER_AUTH
    ) -> ssl.SSLContext:
        """
        Convert TLS configuration to SSL context.

        Args:
            purpose: SSL context purpose

        Returns:
            Configured SSL context

        """
        context = ssl.create_default_context(purpose)

        # Set TLS versions
        context.minimum_version = getattr(ssl, f"TLSVersion.{self.min_version.name}")
        context.maximum_version = getattr(ssl, f"TLSVersion.{self.max_version.name}")

        # Configure certificate
        if self.certificate:
            if self.certificate.cert_file and self.certificate.key_file:
                context.load_cert_chain(
                    certfile=self.certificate.cert_file,
                    keyfile=self.certificate.key_file,
                )
            elif self.certificate.cert_data and self.certificate.key_data:
                # Create temporary files for certificate and key
                import tempfile

                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".pem", delete=False
                ) as cert_file:
                    cert_file.write(self.certificate.cert_data)
                    cert_path = cert_file.name

                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".pem", delete=False
                ) as key_file:
                    key_file.write(self.certificate.key_data)
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

            # Configure CA
            if self.certificate.ca_file:
                context.load_verify_locations(cafile=self.certificate.ca_file)
            elif self.certificate.ca_data:
                context.load_verify_locations(cadata=self.certificate.ca_data)
            elif self.certificate.ca_path:
                context.load_verify_locations(capath=self.certificate.ca_path)

        # Configure validation
        if (
            self.certificate
            and self.certificate.validation_mode == CertificateValidationMode.NONE
        ):
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        elif (
            self.certificate
            and self.certificate.validation_mode == CertificateValidationMode.STRICT
        ):
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
        else:
            context.check_hostname = (
                self.certificate.verify_hostname if self.certificate else True
            )
            context.verify_mode = (
                ssl.CERT_REQUIRED
                if (self.certificate and self.certificate.verify_peer)
                else ssl.CERT_NONE
            )

        # Configure cipher suites
        if self.cipher_suites:
            context.set_ciphers(":".join(self.cipher_suites))

        if self.prefer_server_ciphers:
            context.options |= ssl.OP_CIPHER_SERVER_PREFERENCE

        # Configure session management (if supported)
        if hasattr(context, "session_cache_size"):
            context.session_cache_size = self.session_cache_size  # type: ignore
        if hasattr(context, "session_timeout"):
            context.session_timeout = self.session_timeout  # type: ignore

        # Configure security options
        if self.insecure_skip_verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        if not self.allow_insecure_ciphers:
            context.options |= ssl.OP_NO_SSLv2
            context.options |= ssl.OP_NO_SSLv3
            context.options |= ssl.OP_NO_TLSv1
            context.options |= ssl.OP_NO_TLSv1_1

        # Configure ALPN
        if self.alpn_protocols:
            context.set_alpn_protocols(self.alpn_protocols)

        # Configure client authentication
        if self.client_auth:
            context.verify_mode = ssl.CERT_REQUIRED
            if self.client_ca_file:
                context.load_verify_locations(cafile=self.client_ca_file)

        # Configure performance options
        if not self.renegotiation:
            context.options |= ssl.OP_NO_RENEGOTIATION

        if not self.compression:
            context.options |= ssl.OP_NO_COMPRESSION

        return context


@dataclass
class WebSocketTLSConfig:
    """WebSocket-specific TLS configuration."""

    # Basic TLS settings
    tls_config: TLSConfig | None = None

    # AutoTLS settings
    autotls_enabled: bool = False
    autotls_domain: str = "libp2p.local"
    autotls_storage_path: str = "autotls-certs"

    # WebSocket-specific settings
    websocket_subprotocols: list[str] = field(default_factory=lambda: ["libp2p"])
    websocket_compression: bool = True
    websocket_max_message_size: int = 32 * 1024 * 1024  # 32MB

    # Connection settings
    handshake_timeout: float = 15.0
    close_timeout: float = 5.0

    def validate(self) -> None:
        """Validate WebSocket TLS configuration."""
        if self.tls_config:
            self.tls_config.validate()

        if self.handshake_timeout <= 0:
            raise ValueError("handshake_timeout must be positive")

        if self.close_timeout <= 0:
            raise ValueError("close_timeout must be positive")

        if self.websocket_max_message_size <= 0:
            raise ValueError("websocket_max_message_size must be positive")

    def get_ssl_context(
        self,
        peer_id: ID | None = None,
        sni_name: str | None = None,
    ) -> ssl.SSLContext | None:
        """
        Get SSL context for WebSocket connection.

        Args:
            peer_id: Peer ID for AutoTLS
            sni_name: SNI name for certificate selection

        Returns:
            SSL context or None if TLS is disabled

        """
        if not self.tls_config and not self.autotls_enabled:
            return None

        # Use AutoTLS if enabled
        if self.autotls_enabled and peer_id:
            from .autotls import get_autotls_manager

            manager = get_autotls_manager()
            if manager:
                domain = sni_name or self.autotls_domain
                return manager.get_ssl_context(peer_id, domain)

        # Use manual TLS configuration
        if self.tls_config:
            return self.tls_config.to_ssl_context()

        return None


# Import Path here to avoid circular imports
from pathlib import Path  # noqa: E402
