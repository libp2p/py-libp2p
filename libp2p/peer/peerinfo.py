from typing import List

import multiaddr

from .id import ID
from .peerdata import PeerData


class PeerInfo:

    peer_id: ID
    addrs: List[multiaddr.Multiaddr]

    def __init__(self, peer_id: ID, peer_data: PeerData = None) -> None:
        self.peer_id = peer_id
        self.addrs = peer_data.get_addrs() if peer_data else None


def info_from_p2p_addr(addr: multiaddr.Multiaddr) -> PeerInfo:
    if not addr:
        raise InvalidAddrError("`addr` should not be `None`")

    if not isinstance(addr, multiaddr.Multiaddr):
        raise InvalidAddrError(f"`addr`={addr} should be of type `Multiaddr`")

    parts = addr.split()
    if not parts:
        raise InvalidAddrError(
            f"`parts`={parts} should at least have a protocol `P_P2P`"
        )

    p2p_part = parts[-1]
    last_protocol_code = p2p_part.protocols()[0].code
    if last_protocol_code != multiaddr.protocols.P_P2P:
        raise InvalidAddrError(
            f"The last protocol should be `P_P2P` instead of `{last_protocol_code}`"
        )

    # make sure the /p2p value parses as a peer.ID
    peer_id_str: str = p2p_part.value_for_protocol(multiaddr.protocols.P_P2P)
    peer_id: ID = ID.from_base58(peer_id_str)

    # we might have received just an / p2p part, which means there's no addr.
    if len(parts) > 1:
        addr = multiaddr.Multiaddr.join(*parts[:-1])

    peer_data = PeerData()
    peer_data.add_addrs([addr])
    peer_data.set_protocols([p.code for p in addr.protocols()])

    return PeerInfo(peer_id, peer_data)


class InvalidAddrError(ValueError):
    pass
