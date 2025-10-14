from collections.abc import (
    Sequence,
)
import ipaddress
import os
from typing import (
    NamedTuple,
)

import multiaddr

from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.pubsub import (
    floodsub,
    gossipsub,
)

# Just a arbitrary large number.
# It is used when calling `MplexStream.read(MAX_READ_LEN)`,
#   to avoid `MplexStream.read()`, which blocking reads until EOF.
MAX_READ_LEN = 65535


def _validate_ipv4_address(address: str) -> str:
    """
    Validate that the given address is a valid IPv4 address.

    Args:
        address: The IP address string to validate

    Returns:
        The validated IPv4 address, or "127.0.0.1" if invalid

    """
    try:
        # Validate that it's a valid IPv4 address
        ipaddress.IPv4Address(address)
        return address
    except (ipaddress.AddressValueError, ValueError):
        # If invalid, return the secure default
        return "127.0.0.1"


# Default bind address configuration with environment variable override
# DEFAULT_BIND_ADDRESS defaults to "127.0.0.1" (secure) but can be overridden
# via LIBP2P_BIND environment variable (e.g., "0.0.0.0" for tests)
# Invalid IPv4 addresses will fallback to "127.0.0.1"
DEFAULT_BIND_ADDRESS = _validate_ipv4_address(os.getenv("LIBP2P_BIND", "127.0.0.1"))
LISTEN_MADDR = multiaddr.Multiaddr(f"/ip4/{DEFAULT_BIND_ADDRESS}/tcp/0")


FLOODSUB_PROTOCOL_ID = floodsub.PROTOCOL_ID
GOSSIPSUB_PROTOCOL_ID = gossipsub.PROTOCOL_ID
GOSSIPSUB_PROTOCOL_ID_V1 = gossipsub.PROTOCOL_ID_V11


class GossipsubParams(NamedTuple):
    degree: int = 10
    degree_low: int = 9
    degree_high: int = 11
    direct_peers: Sequence[PeerInfo] = []
    time_to_live: int = 30
    gossip_window: int = 3
    gossip_history: int = 5
    heartbeat_initial_delay: float = 0.1
    heartbeat_interval: float = 0.5
    direct_connect_initial_delay: float = 0.1
    direct_connect_interval: int = 300
    do_px: bool = False
    px_peers_count: int = 16
    prune_back_off: int = 60
    unsubscribe_back_off: int = 10
    flood_publish: bool = False


GOSSIPSUB_PARAMS = GossipsubParams()
