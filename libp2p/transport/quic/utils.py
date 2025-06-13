"""
Multiaddr utilities for QUIC transport - Module 4.
Essential utilities required for QUIC transport implementation.
Based on go-libp2p and js-libp2p QUIC implementations.
"""

import ipaddress

import multiaddr

from libp2p.custom_types import TProtocol

from .config import QUICTransportConfig
from .exceptions import QUICInvalidMultiaddrError, QUICUnsupportedVersionError

# Protocol constants
QUIC_V1_PROTOCOL = QUICTransportConfig.PROTOCOL_QUIC_V1
QUIC_DRAFT29_PROTOCOL = QUICTransportConfig.PROTOCOL_QUIC_DRAFT29
UDP_PROTOCOL = "udp"
IP4_PROTOCOL = "ip4"
IP6_PROTOCOL = "ip6"

# QUIC version to wire format mappings (required for aioquic)
QUIC_VERSION_MAPPINGS = {
    QUIC_V1_PROTOCOL: 0x00000001,  # RFC 9000
    QUIC_DRAFT29_PROTOCOL: 0xFF00001D,  # draft-29
}

# ALPN protocols for libp2p over QUIC
LIBP2P_ALPN_PROTOCOLS = ["libp2p"]


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
            addr_str.endswith(f"/{QUIC_V1_PROTOCOL}")
            or addr_str.endswith(f"/{QUIC_DRAFT29_PROTOCOL}")
            or addr_str.endswith("/quic")
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
            host = maddr.value_for_protocol(multiaddr.protocols.P_IP4)  # type: ignore
        except ValueError:
            pass

        # Try to get IPv6 address if IPv4 not found
        if host is None:
            try:
                host = maddr.value_for_protocol(multiaddr.protocols.P_IP6)  # type: ignore
            except ValueError:
                pass

        # Get UDP port
        try:
            port_str = maddr.value_for_protocol(multiaddr.protocols.P_UDP)  # type: ignore
            port = int(port_str)
        except ValueError:
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
