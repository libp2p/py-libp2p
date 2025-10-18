"""
Multiaddr utilities for QUIC transport - Module 4.
Essential utilities required for QUIC transport implementation.
Based on go-libp2p and js-libp2p QUIC implementations.
"""

import ipaddress
import logging
import ssl

from aioquic.quic.configuration import QuicConfiguration
import multiaddr
import multiaddr.protocols

from libp2p.custom_types import TProtocol
from libp2p.transport.quic.security import QUICTLSConfigManager

from .config import QUICTransportConfig
from .exceptions import QUICInvalidMultiaddrError, QUICUnsupportedVersionError

logger = logging.getLogger(__name__)

# Protocol constants
QUIC_V1_PROTOCOL = QUICTransportConfig.PROTOCOL_QUIC_V1
QUIC_DRAFT29_PROTOCOL = QUICTransportConfig.PROTOCOL_QUIC_DRAFT29
UDP_PROTOCOL = "udp"
IP4_PROTOCOL = "ip4"
IP6_PROTOCOL = "ip6"

SERVER_CONFIG_PROTOCOL_V1 = f"{QUIC_V1_PROTOCOL}_server"
CLIENT_CONFIG_PROTCOL_V1 = f"{QUIC_V1_PROTOCOL}_client"

SERVER_CONFIG_PROTOCOL_DRAFT_29 = f"{QUIC_DRAFT29_PROTOCOL}_server"
CLIENT_CONFIG_PROTOCOL_DRAFT_29 = f"{QUIC_DRAFT29_PROTOCOL}_client"

CUSTOM_QUIC_VERSION_MAPPING: dict[str, int] = {
    SERVER_CONFIG_PROTOCOL_V1: 0x00000001,  # RFC 9000
    CLIENT_CONFIG_PROTCOL_V1: 0x00000001,  # RFC 9000
    SERVER_CONFIG_PROTOCOL_DRAFT_29: 0xFF00001D,  # draft-29
    CLIENT_CONFIG_PROTOCOL_DRAFT_29: 0xFF00001D,  # draft-29
}

# QUIC version to wire format mappings (required for aioquic)
QUIC_VERSION_MAPPINGS: dict[TProtocol, int] = {
    QUIC_V1_PROTOCOL: 0x00000001,  # RFC 9000
    QUIC_DRAFT29_PROTOCOL: 0xFF00001D,  # draft-29
}

# ALPN protocols for libp2p over QUIC
LIBP2P_ALPN_PROTOCOLS: list[str] = ["libp2p"]


def is_quic_multiaddr(maddr: multiaddr.Multiaddr) -> bool:
    """
    Check if a multiaddr represents a QUIC address.

    Valid QUIC multiaddrs:
    - /ip4/127.0.0.1/udp/4001/quic-v1
    - /ip4/127.0.0.1/udp/4001/quic
    - /ip6/::1/udp/4001/quic-v1
    - /ip6/::1/udp/4001/quic

    Args:
        maddr: Multiaddr to check

    Returns:
        True if the multiaddr represents a QUIC address

    """
    try:
        addr_str = str(maddr)

        # Check for required components
        has_ip = f"/{IP4_PROTOCOL}/" in addr_str or f"/{IP6_PROTOCOL}/" in addr_str
        has_udp = f"/{UDP_PROTOCOL}/" in addr_str
        has_quic = (
            f"/{QUIC_V1_PROTOCOL}" in addr_str
            or f"/{QUIC_DRAFT29_PROTOCOL}" in addr_str
            or "/quic" in addr_str
        )

        return has_ip and has_udp and has_quic

    except Exception:
        return False


def quic_multiaddr_to_endpoint(maddr: multiaddr.Multiaddr) -> tuple[str, int]:
    """
    Extract host and port from a QUIC multiaddr.

    Args:
        maddr: QUIC multiaddr

    Returns:
        Tuple of (host, port)

    Raises:
        QUICInvalidMultiaddrError: If multiaddr is not a valid QUIC address

    """
    if not is_quic_multiaddr(maddr):
        raise QUICInvalidMultiaddrError(f"Not a valid QUIC multiaddr: {maddr}")

    try:
        host = None
        port = None

        # Try to get IPv4 address
        try:
            host = maddr.value_for_protocol(multiaddr.protocols.P_IP4)
        except Exception:
            pass

        # Try to get IPv6 address if IPv4 not found
        if host is None:
            try:
                host = maddr.value_for_protocol(multiaddr.protocols.P_IP6)
            except Exception:
                pass

        # Get UDP port
        try:
            port_str = maddr.value_for_protocol(multiaddr.protocols.P_UDP)
            if port_str is not None:
                port = int(port_str)
        except Exception:
            pass

        if host is None or port is None:
            raise QUICInvalidMultiaddrError(f"Could not extract host/port from {maddr}")

        return host, port

    except Exception as e:
        raise QUICInvalidMultiaddrError(
            f"Failed to parse QUIC multiaddr {maddr}: {e}"
        ) from e


def multiaddr_to_quic_version(maddr: multiaddr.Multiaddr) -> TProtocol:
    """
    Determine QUIC version from multiaddr.

    Args:
        maddr: QUIC multiaddr

    Returns:
        QUIC version identifier ("quic-v1" or "quic")

    Raises:
        QUICInvalidMultiaddrError: If multiaddr doesn't contain QUIC protocol

    """
    try:
        addr_str = str(maddr)

        if f"/{QUIC_V1_PROTOCOL}" in addr_str:
            return QUIC_V1_PROTOCOL  # RFC 9000
        elif f"/{QUIC_DRAFT29_PROTOCOL}" in addr_str:
            return QUIC_DRAFT29_PROTOCOL  # draft-29
        else:
            raise QUICInvalidMultiaddrError(f"No QUIC protocol found in {maddr}")

    except Exception as e:
        raise QUICInvalidMultiaddrError(
            f"Failed to determine QUIC version from {maddr}: {e}"
        ) from e


def create_quic_multiaddr(
    host: str, port: int, version: str = "quic-v1"
) -> multiaddr.Multiaddr:
    """
    Create a QUIC multiaddr from host, port, and version.

    Args:
        host: IP address (IPv4 or IPv6)
        port: UDP port number
        version: QUIC version ("quic-v1" or "quic")

    Returns:
        QUIC multiaddr

    Raises:
        QUICInvalidMultiaddrError: If invalid parameters provided

    """
    try:
        # Determine IP version
        try:
            ip = ipaddress.ip_address(host)
            if isinstance(ip, ipaddress.IPv4Address):
                ip_proto = IP4_PROTOCOL
            else:
                ip_proto = IP6_PROTOCOL
        except ValueError:
            raise QUICInvalidMultiaddrError(f"Invalid IP address: {host}")

        # Validate port
        if not (0 <= port <= 65535):
            raise QUICInvalidMultiaddrError(f"Invalid port: {port}")

        # Validate and normalize QUIC version
        if version == "quic-v1" or version == "/quic-v1":
            quic_proto = QUIC_V1_PROTOCOL
        elif version == "quic" or version == "/quic":
            quic_proto = QUIC_DRAFT29_PROTOCOL
        else:
            raise QUICInvalidMultiaddrError(f"Invalid QUIC version: {version}")

        # Construct multiaddr
        addr_str = f"/{ip_proto}/{host}/{UDP_PROTOCOL}/{port}/{quic_proto}"
        return multiaddr.Multiaddr(addr_str)

    except Exception as e:
        raise QUICInvalidMultiaddrError(f"Failed to create QUIC multiaddr: {e}") from e


def quic_version_to_wire_format(version: TProtocol) -> int:
    """
    Convert QUIC version string to wire format integer for aioquic.

    Args:
        version: QUIC version string ("quic-v1" or "quic")

    Returns:
        Wire format version number

    Raises:
        QUICUnsupportedVersionError: If version is not supported

    """
    wire_version = QUIC_VERSION_MAPPINGS.get(version)
    if wire_version is None:
        raise QUICUnsupportedVersionError(f"Unsupported QUIC version: {version}")

    return wire_version


def custom_quic_version_to_wire_format(version: TProtocol) -> int:
    """
    Convert QUIC version string to wire format integer for aioquic.

    Args:
        version: QUIC version string ("quic-v1" or "quic")

    Returns:
        Wire format version number

    Raises:
        QUICUnsupportedVersionError: If version is not supported

    """
    wire_version = CUSTOM_QUIC_VERSION_MAPPING.get(version)
    if wire_version is None:
        raise QUICUnsupportedVersionError(f"Unsupported QUIC version: {version}")

    return wire_version


def get_alpn_protocols() -> list[str]:
    """
    Get ALPN protocols for libp2p over QUIC.

    Returns:
        List of ALPN protocol identifiers

    """
    return LIBP2P_ALPN_PROTOCOLS.copy()


def normalize_quic_multiaddr(maddr: multiaddr.Multiaddr) -> multiaddr.Multiaddr:
    """
    Normalize a QUIC multiaddr to canonical form.

    Args:
        maddr: Input QUIC multiaddr

    Returns:
        Normalized multiaddr

    Raises:
        QUICInvalidMultiaddrError: If not a valid QUIC multiaddr

    """
    if not is_quic_multiaddr(maddr):
        raise QUICInvalidMultiaddrError(f"Not a QUIC multiaddr: {maddr}")

    host, port = quic_multiaddr_to_endpoint(maddr)
    version = multiaddr_to_quic_version(maddr)

    return create_quic_multiaddr(host, port, version)


def create_server_config_from_base(
    base_config: QuicConfiguration,
    security_manager: QUICTLSConfigManager | None = None,
    transport_config: QUICTransportConfig | None = None,
) -> QuicConfiguration:
    """
    Create a server configuration without using deepcopy.
    Manually copies attributes while handling cryptography objects properly.
    """
    try:
        # Create new server configuration from scratch
        server_config = QuicConfiguration(is_client=False)
        server_config.verify_mode = ssl.CERT_NONE

        # Copy basic configuration attributes (these are safe to copy)
        copyable_attrs = [
            "alpn_protocols",
            "verify_mode",
            "max_datagram_frame_size",
            "idle_timeout",
            "max_concurrent_streams",
            "supported_versions",
            "max_data",
            "max_stream_data",
            "stateless_retry",
            "quantum_readiness_test",
        ]

        for attr in copyable_attrs:
            if hasattr(base_config, attr):
                value = getattr(base_config, attr)
                if value is not None:
                    setattr(server_config, attr, value)

        # Handle cryptography objects - these need direct reference, not copying
        crypto_attrs = [
            "certificate",
            "private_key",
            "certificate_chain",
            "ca_certs",
        ]

        for attr in crypto_attrs:
            if hasattr(base_config, attr):
                value = getattr(base_config, attr)
                if value is not None:
                    setattr(server_config, attr, value)

        # Apply security manager configuration if available
        if security_manager:
            try:
                server_tls_config = security_manager.create_server_config()

                # Override with security manager's TLS configuration
                if server_tls_config.certificate:
                    server_config.certificate = server_tls_config.certificate
                if server_tls_config.private_key:
                    server_config.private_key = server_tls_config.private_key
                if server_tls_config.certificate_chain:
                    server_config.certificate_chain = (
                        server_tls_config.certificate_chain
                    )
                if server_tls_config.alpn_protocols:
                    server_config.alpn_protocols = server_tls_config.alpn_protocols
                server_tls_config.request_client_certificate = True

            except Exception as e:
                logger.warning(f"Failed to apply security manager config: {e}")

        # Set transport-specific defaults if provided
        if transport_config:
            if server_config.idle_timeout == 0:
                server_config.idle_timeout = getattr(
                    transport_config, "idle_timeout", 30.0
                )
            if server_config.max_datagram_frame_size is None:
                server_config.max_datagram_frame_size = getattr(
                    transport_config, "max_datagram_size", 1200
                )
        # Ensure we have ALPN protocols
        if not server_config.alpn_protocols:
            server_config.alpn_protocols = ["libp2p"]

        logger.debug("Successfully created server config without deepcopy")
        return server_config

    except Exception as e:
        logger.error(f"Failed to create server config: {e}")
        raise


def create_client_config_from_base(
    base_config: QuicConfiguration,
    security_manager: QUICTLSConfigManager | None = None,
    transport_config: QUICTransportConfig | None = None,
) -> QuicConfiguration:
    """
    Create a client configuration without using deepcopy.
    """
    try:
        # Create new client configuration from scratch
        client_config = QuicConfiguration(is_client=True)
        client_config.verify_mode = ssl.CERT_NONE

        # Copy basic configuration attributes
        copyable_attrs = [
            "alpn_protocols",
            "verify_mode",
            "max_datagram_frame_size",
            "idle_timeout",
            "max_concurrent_streams",
            "supported_versions",
            "max_data",
            "max_stream_data",
            "quantum_readiness_test",
        ]

        for attr in copyable_attrs:
            if hasattr(base_config, attr):
                value = getattr(base_config, attr)
                if value is not None:
                    setattr(client_config, attr, value)

        # Handle cryptography objects - these need direct reference, not copying
        crypto_attrs = [
            "certificate",
            "private_key",
            "certificate_chain",
            "ca_certs",
        ]

        for attr in crypto_attrs:
            if hasattr(base_config, attr):
                value = getattr(base_config, attr)
                if value is not None:
                    setattr(client_config, attr, value)

        # Apply security manager configuration if available
        if security_manager:
            try:
                client_tls_config = security_manager.create_client_config()

                # Override with security manager's TLS configuration
                if client_tls_config.certificate:
                    client_config.certificate = client_tls_config.certificate
                if client_tls_config.private_key:
                    client_config.private_key = client_tls_config.private_key
                if client_tls_config.certificate_chain:
                    client_config.certificate_chain = (
                        client_tls_config.certificate_chain
                    )
                if client_tls_config.alpn_protocols:
                    client_config.alpn_protocols = client_tls_config.alpn_protocols

            except Exception as e:
                logger.warning(f"Failed to apply security manager config: {e}")

        # Ensure we have ALPN protocols
        if not client_config.alpn_protocols:
            client_config.alpn_protocols = ["libp2p"]

        logger.debug("Successfully created client config without deepcopy")
        return client_config

    except Exception as e:
        logger.error(f"Failed to create client config: {e}")
        raise
