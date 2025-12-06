from collections.abc import (
    Sequence,
)
from typing import (
    Any,
)

import multiaddr

from .id import (
    ID,
)


class PeerInfo:
    peer_id: ID
    addrs: list[multiaddr.Multiaddr]

    def __init__(self, peer_id: ID, addrs: Sequence[multiaddr.Multiaddr]) -> None:
        self.peer_id = peer_id
        self.addrs = list(addrs)

    def __eq__(self, other: Any) -> bool:
        return (
            isinstance(other, PeerInfo)
            and self.peer_id == other.peer_id
            and self.addrs == other.addrs
        )


def info_from_p2p_addr(addr: multiaddr.Multiaddr) -> PeerInfo:
    if not addr:
        raise InvalidAddrError("`addr` should not be `None`")

    # Manual parsing because multiaddr==0.0.11 doesn't have .split()
    protocols = addr.protocols()
    if not protocols:
        raise InvalidAddrError("Address has no protocols")

    last_protocol = protocols[-1]

    # P_IPFS = 421, P_P2P = 421
    if last_protocol.code != 421:
        raise InvalidAddrError(
            f"The last protocol should be `P_P2P` instead of `{last_protocol.code}`"
        )

    peer_id_str = addr.value_for_protocol(last_protocol.code)
    if peer_id_str is None:
        raise InvalidAddrError("Missing value for /p2p protocol in multiaddr")

    peer_id = ID.from_base58(peer_id_str)

    if len(protocols) > 1:
        # Reconstruct the p2p part to decapsulate it
        # We use the name from the protocol to be safe (ipfs vs p2p)
        p2p_part = multiaddr.Multiaddr(f"/{last_protocol.name}/{peer_id_str}")
        transport_addr = addr.decapsulate(p2p_part)
        return PeerInfo(peer_id, [transport_addr])
    else:
        # Only p2p part exists
        return PeerInfo(peer_id, [addr])


def peer_info_to_bytes(peer_info: PeerInfo) -> bytes:
    lines = [str(peer_info.peer_id)] + [str(addr) for addr in peer_info.addrs]
    return "\n".join(lines).encode("utf-8")


def peer_info_from_bytes(data: bytes) -> PeerInfo:
    try:
        lines = data.decode("utf-8").splitlines()
        if not lines:
            raise InvalidAddrError("no data to decode PeerInfo")

        peer_id = ID.from_base58(lines[0])
        addrs = [multiaddr.Multiaddr(addr_str) for addr_str in lines[1:]]
        return PeerInfo(peer_id, addrs)
    except Exception as e:
        raise InvalidAddrError(f"failed to decode PeerInfo: {e}")


class InvalidAddrError(ValueError):
    pass
