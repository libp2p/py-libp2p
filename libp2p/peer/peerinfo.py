from collections.abc import (
    Sequence,
)
from typing import (
    Any,
    cast,
)

import multiaddr
from multiaddr.protocols import (
    P_P2P,
    Protocol,
)

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

    protocols = addr.protocols()
    if not protocols:
        raise InvalidAddrError(f"`addr`={addr} should at least have a protocol `P_P2P`")

    last_protocol = cast(Protocol, protocols[-1])

    if last_protocol is None:
        raise InvalidAddrError("The last protocol is None")

    last_protocol_code = last_protocol.code
    if last_protocol_code != P_P2P:
        raise InvalidAddrError(
            f"The last protocol should be `P_P2P` instead of `{last_protocol_code}`"
        )

    # make sure the /p2p value parses as a peer.ID
    peer_id_str = addr.value_for_protocol(P_P2P)
    if peer_id_str is None:
        raise InvalidAddrError("Missing value for /p2p protocol in multiaddr")

    peer_id: ID = ID.from_base58(peer_id_str)

    # we might have received just an / p2p part, which means there's no addr.
    # Construct the p2p part to decapsulate it
    p2p_part = multiaddr.Multiaddr(f"/p2p/{peer_id_str}")
    transport_addr = addr.decapsulate(p2p_part)

    if not transport_addr.protocols():
        # If transport_addr is empty, it means the input was just the p2p part.
        # In this case we return the original address as the address list.
        return PeerInfo(peer_id, [addr])

    return PeerInfo(peer_id, [transport_addr])


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
