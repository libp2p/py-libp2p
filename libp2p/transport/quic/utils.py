"""
Multiaddr utilities for QUIC transport.
Handles QUIC-specific multiaddr parsing and validation.
"""

import multiaddr

from libp2p.custom_types import TProtocol

from .config import QUICTransportConfig

QUIC_V1_PROTOCOL = QUICTransportConfig.PROTOCOL_QUIC_V1
QUIC_DRAFT29_PROTOCOL = QUICTransportConfig.PROTOCOL_QUIC_DRAFT29
UDP_PROTOCOL = "udp"
IP4_PROTOCOL = "ip4"
IP6_PROTOCOL = "ip6"


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
        # Get protocol names from the multiaddr string
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
        ValueError: If multiaddr is not a valid QUIC address

    """
    if not is_quic_multiaddr(maddr):
        raise ValueError(f"Not a valid QUIC multiaddr: {maddr}")

    try:
        # Use multiaddr's value_for_protocol method to extract values
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
            # The the package is exposed by types not availble
            port_str = maddr.value_for_protocol(multiaddr.protocols.P_UDP)  # type: ignore
            port = int(port_str)
        except ValueError:
            pass

        if host is None or port is None:
            raise ValueError(f"Could not extract host/port from {maddr}")

        return host, port

    except Exception as e:
        raise ValueError(f"Failed to parse QUIC multiaddr {maddr}: {e}") from e


def multiaddr_to_quic_version(maddr: multiaddr.Multiaddr) -> TProtocol:
    """
    Determine QUIC version from multiaddr.

    Args:
        maddr: QUIC multiaddr

    Returns:
        QUIC version identifier ("/quic-v1" or "/quic")

    Raises:
        ValueError: If multiaddr doesn't contain QUIC protocol

    """
    try:
        addr_str = str(maddr)

        if f"/{QUIC_V1_PROTOCOL}" in addr_str:
            return QUIC_V1_PROTOCOL  # RFC 9000
        elif f"/{QUIC_DRAFT29_PROTOCOL}" in addr_str:
            return QUIC_DRAFT29_PROTOCOL  # draft-29
        else:
            raise ValueError(f"No QUIC protocol found in {maddr}")

    except Exception as e:
        raise ValueError(f"Failed to determine QUIC version from {maddr}: {e}") from e


def create_quic_multiaddr(
    host: str, port: int, version: str = "/quic-v1"
) -> multiaddr.Multiaddr:
    """
    Create a QUIC multiaddr from host, port, and version.

    Args:
        host: IP address (IPv4 or IPv6)
        port: UDP port number
        version: QUIC version ("/quic-v1" or "/quic")

    Returns:
        QUIC multiaddr

    Raises:
        ValueError: If invalid parameters provided

    """
    try:
        import ipaddress

        # Determine IP version
        try:
            ip = ipaddress.ip_address(host)
            if isinstance(ip, ipaddress.IPv4Address):
                ip_proto = IP4_PROTOCOL
            else:
                ip_proto = IP6_PROTOCOL
        except ValueError:
            raise ValueError(f"Invalid IP address: {host}")

        # Validate port
        if not (0 <= port <= 65535):
            raise ValueError(f"Invalid port: {port}")

        # Validate QUIC version
        if version not in ["/quic-v1", "/quic"]:
            raise ValueError(f"Invalid QUIC version: {version}")

        # Construct multiaddr
        quic_proto = (
            QUIC_V1_PROTOCOL if version == "/quic-v1" else QUIC_DRAFT29_PROTOCOL
        )
        addr_str = f"/{ip_proto}/{host}/{UDP_PROTOCOL}/{port}/{quic_proto}"

        return multiaddr.Multiaddr(addr_str)

    except Exception as e:
        raise ValueError(f"Failed to create QUIC multiaddr: {e}") from e


def is_quic_v1_multiaddr(maddr: multiaddr.Multiaddr) -> bool:
    """Check if multiaddr uses QUIC v1 (RFC 9000)."""
    try:
        return multiaddr_to_quic_version(maddr) == "/quic-v1"
    except ValueError:
        return False


def is_quic_draft29_multiaddr(maddr: multiaddr.Multiaddr) -> bool:
    """Check if multiaddr uses QUIC draft-29."""
    try:
        return multiaddr_to_quic_version(maddr) == "/quic"
    except ValueError:
        return False


def normalize_quic_multiaddr(maddr: multiaddr.Multiaddr) -> multiaddr.Multiaddr:
    """
    Normalize a QUIC multiaddr to canonical form.

    Args:
        maddr: Input QUIC multiaddr

    Returns:
        Normalized multiaddr

    Raises:
        ValueError: If not a valid QUIC multiaddr

    """
    if not is_quic_multiaddr(maddr):
        raise ValueError(f"Not a QUIC multiaddr: {maddr}")

    host, port = quic_multiaddr_to_endpoint(maddr)
    version = multiaddr_to_quic_version(maddr)

    return create_quic_multiaddr(host, port, version)
