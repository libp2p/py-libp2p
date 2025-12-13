"""
Address management for connection dialing.

This module provides address sorting, filtering, and selection logic
matching JavaScript libp2p behavior.

Reference: https://github.com/libp2p/js-libp2p/blob/main/packages/libp2p/src/connection-manager/address-sorter.ts
"""

from collections.abc import Callable
import ipaddress
import logging
from typing import TYPE_CHECKING, Any

from multiaddr import Multiaddr

if TYPE_CHECKING:
    from libp2p.peer.id import ID

logger = logging.getLogger("libp2p.network.address_manager")


def extract_ip_from_multiaddr(addr: Multiaddr) -> str | None:
    """
    Extract the IP address from a multiaddr.

    Uses multiaddr's value_for_protocol method to extract IP addresses.

    Parameters
    ----------
    addr : Multiaddr
        Multiaddr to extract from

    Returns
    -------
    str | None
        IP address or None if not found

    """
    from multiaddr.exceptions import ProtocolLookupError

    # Try IPv4 first
    try:
        return addr.value_for_protocol("ip4")
    except ProtocolLookupError:
        pass

    # Try IPv6
    try:
        return addr.value_for_protocol("ip6")
    except ProtocolLookupError:
        pass

    return None


def is_private_ip(ip_str: str) -> bool:
    """
    Check if an IP address is private.

    Parameters
    ----------
    ip_str : str
        IP address string

    Returns
    -------
    bool
        True if IP is private

    """
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private
    except ValueError:
        return False


def is_loopback_ip(ip_str: str) -> bool:
    """
    Check if an IP address is loopback.

    Parameters
    ----------
    ip_str : str
        IP address string

    Returns
    -------
    bool
        True if IP is loopback

    """
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_loopback
    except ValueError:
        return False


def is_circuit_relay_address(addr: Multiaddr) -> bool:
    """
    Check if address is a circuit relay address.

    Parameters
    ----------
    addr : Multiaddr
        Multiaddr to check

    Returns
    -------
    bool
        True if address is a circuit relay address

    """
    addr_str = str(addr)
    return "/p2p-circuit/" in addr_str


def is_certified_address(addr: Multiaddr) -> bool:
    """
    Check if address is certified (has peer record).

    Parameters
    ----------
    addr : Multiaddr
        Multiaddr to check

    Returns
    -------
    bool
        True if address appears to be certified

    Note: Full certification checking requires peer store access.
    This is a simplified check based on address format.

    """
    # In JS libp2p, certified addresses have a specific format
    # For now, we'll check if the address has certain properties
    # TODO: Implement proper certification checking when peer records
    # are fully integrated
    return False


def get_transport_priority(addr: Multiaddr) -> int:
    """
    Get transport priority for sorting.

    Higher priority = more reliable transport.

    Parameters
    ----------
    addr : Multiaddr
        Multiaddr to check

    Returns
    -------
    int
        Priority value (higher = better)

    """
    addr_str = str(addr).lower()

    # Transport priority (higher = more reliable)
    # TCP > WebSocketSecure > WebSocket > WebRTC > WebRTCDirect > WebTransport
    if "/tcp/" in addr_str:
        return 100
    elif "/wss/" in addr_str or "/ws/" in addr_str and "/tls/" in addr_str:
        return 80
    elif "/ws/" in addr_str:
        return 60
    elif "/webrtc/" in addr_str:
        return 40
    elif "/webrtc-direct/" in addr_str:
        return 20
    elif "/webtransport/" in addr_str:
        return 10

    # Default priority for unknown transports
    return 0


def default_address_sorter(addresses: list[Multiaddr]) -> list[Multiaddr]:
    """
    Default address sorter matching JS libp2p behavior.

    Sorting order (stable sort, applied in reverse order):
    1. Loopback addresses last
    2. Public addresses before private
    3. Circuit relay addresses last
    4. Certified addresses first
    5. Transport reliability (handled separately if needed)

    Parameters
    ----------
    addresses : list[Multiaddr]
        List of addresses to sort

    Returns
    -------
    list[Multiaddr]
        Sorted list of addresses

    """
    # Create list with address info for sorting
    addr_data: list[dict[str, Any]] = []

    for addr in addresses:
        ip_str = extract_ip_from_multiaddr(addr)
        is_private = is_private_ip(ip_str) if ip_str else False
        is_loopback = is_loopback_ip(ip_str) if ip_str else False
        is_circuit = is_circuit_relay_address(addr)
        is_certified = is_certified_address(addr)
        transport_priority = get_transport_priority(addr)

        addr_data.append(
            {
                "addr": addr,
                "is_loopback": is_loopback,
                "is_private": is_private,
                "is_circuit": is_circuit,
                "is_certified": is_certified,
                "transport_priority": transport_priority,
            }
        )

    # Stable sort in reverse order (last sort is most important)
    # 1. Sort by loopback (loopback last)
    addr_data.sort(key=lambda x: int(x["is_loopback"]))

    # 2. Sort by public/private (public first)
    addr_data.sort(key=lambda x: int(x["is_private"]))

    # 3. Sort by circuit relay (circuit last)
    addr_data.sort(key=lambda x: int(x["is_circuit"]))

    # 4. Sort by certified (certified first)
    addr_data.sort(key=lambda x: int(not x["is_certified"]))

    # 5. Sort by transport priority (higher priority first)
    addr_data.sort(key=lambda x: -x["transport_priority"])

    return [item["addr"] for item in addr_data]


class AddressManager:
    """
    Manages address sorting, filtering, and selection for dialing.

    Provides address management functionality matching JS libp2p behavior.
    """

    def __init__(
        self,
        address_sorter: (Callable[[list[Multiaddr]], list[Multiaddr]] | None) = None,
        connection_gate: Any | None = None,
    ):
        """
        Initialize address manager.

        Parameters
        ----------
        address_sorter : callable | None
            Custom address sorter function. If None, uses default sorter.
        connection_gate : ConnectionGater | None
            Connection gater for filtering addresses

        """
        self.address_sorter = address_sorter or default_address_sorter
        self.connection_gate = connection_gate

    def filter_addresses(
        self,
        addresses: list[Multiaddr],
        peer_id: "ID | None" = None,
    ) -> list[Multiaddr]:
        """
        Filter addresses based on connection gater.

        Parameters
        ----------
        addresses : list[Multiaddr]
            List of addresses to filter
        peer_id : ID | None
            Peer ID for gating checks

        Returns
        -------
        list[Multiaddr]
            Filtered list of addresses

        """
        if not self.connection_gate:
            return addresses

        filtered = []
        for addr in addresses:
            # Check if dialing this multiaddr is allowed
            if self.connection_gate is not None and hasattr(
                self.connection_gate, "deny_dial_multiaddr"
            ):
                try:
                    if self.connection_gate.deny_dial_multiaddr(addr):
                        logger.debug(f"Address {addr} denied by connection gater")
                        continue
                except Exception as e:
                    logger.debug(f"Error checking multiaddr gating: {e}")
                    # On error, allow the address
                    pass

            # Check if dialing this peer is allowed
            if (
                peer_id
                and self.connection_gate is not None
                and hasattr(self.connection_gate, "deny_dial_peer")
            ):
                try:
                    if self.connection_gate.deny_dial_peer(peer_id):
                        logger.debug(f"Peer {peer_id} denied by connection gater")
                        continue
                except Exception as e:
                    logger.debug(f"Error checking peer gating: {e}")
                    # On error, allow the peer
                    pass

            filtered.append(addr)

        return filtered

    def sort_addresses(self, addresses: list[Multiaddr]) -> list[Multiaddr]:
        """
        Sort addresses using configured sorter.

        Parameters
        ----------
        addresses : list[Multiaddr]
            List of addresses to sort

        Returns
        -------
        list[Multiaddr]
            Sorted list of addresses

        """
        return self.address_sorter(addresses)

    def prepare_addresses(
        self,
        addresses: list[Multiaddr],
        peer_id: "ID | None" = None,
        max_addresses: int | None = None,
    ) -> list[Multiaddr]:
        """
        Prepare addresses for dialing: filter, sort, and limit.

        Parameters
        ----------
        addresses : list[Multiaddr]
            List of addresses to prepare
        peer_id : ID | None
            Peer ID for gating checks
        max_addresses : int | None
            Maximum number of addresses to return

        Returns
        -------
        list[Multiaddr]
            Prepared list of addresses

        """
        # Filter by connection gater
        filtered = self.filter_addresses(addresses, peer_id)

        # Sort addresses
        sorted_addrs = self.sort_addresses(filtered)

        # Limit number of addresses
        if max_addresses is not None and max_addresses > 0:
            sorted_addrs = sorted_addrs[:max_addresses]

        return sorted_addrs
