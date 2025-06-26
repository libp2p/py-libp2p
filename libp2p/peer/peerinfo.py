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

    parts: list[multiaddr.Multiaddr] = addr.split()
    if not parts:
        raise InvalidAddrError(
            f"`parts`={parts} should at least have a protocol `P_P2P`"
        )

    p2p_part = parts[-1]
    p2p_protocols = p2p_part.protocols()
    if not p2p_protocols:
        raise InvalidAddrError("The last part of the address has no protocols")
    last_protocol = p2p_protocols[0]
    if last_protocol is None:
        raise InvalidAddrError("The last protocol is None")

    last_protocol_code = last_protocol.code
    if last_protocol_code != multiaddr.multiaddr.protocols.P_P2P:
        raise InvalidAddrError(
            f"The last protocol should be `P_P2P` instead of `{last_protocol_code}`"
        )

    # make sure the /p2p value parses as a peer.ID
    peer_id_str = p2p_part.value_for_protocol(multiaddr.multiaddr.protocols.P_P2P)
    if peer_id_str is None:
        raise InvalidAddrError("Missing value for /p2p protocol in multiaddr")

    peer_id: ID = ID.from_base58(peer_id_str)

    # we might have received just an / p2p part, which means there's no addr.
    if len(parts) > 1:
        addr = multiaddr.Multiaddr.join(*parts[:-1])

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
