import multiaddr

from .id import id_b58_decode
from .peerdata import PeerData


class PeerInfo:
    # pylint: disable=too-few-public-methods
    def __init__(self, peer_id, peer_data=None):
        self.peer_id = peer_id
        self.addrs = peer_data.get_addrs() if peer_data else None


def info_from_p2p_addr(addr: multiaddr.Multiaddr) -> PeerInfo:
    if not addr:
        raise InvalidAddrError("addr should not be None")

    if not isinstance(addr, multiaddr.Multiaddr):
        raise InvalidAddrError(f"addr={addr} should be in type Multiaddr")

    parts = addr.split()
    if not parts:
        raise InvalidAddrError()

    p2p_part = parts[-1]
    last_protocol_code = p2p_part.protocols()[0].code
    if last_protocol_code != multiaddr.protocols.P_P2P:
        raise InvalidAddrError(
            f"the last protocol should be P_P2P instead of {last_protocol_code}"
        )

    # make sure the /p2p value parses as a peer.ID
    peer_id_str = p2p_part.value_for_protocol(multiaddr.protocols.P_P2P)
    peer_id = id_b58_decode(peer_id_str)

    # we might have received just an / p2p part, which means there's no addr.
    if len(parts) > 1:
        addr = multiaddr.Multiaddr.join(*parts[:-1])

    peer_data = PeerData()
    peer_data.addrs = [addr]
    peer_data.protocols = [p.code for p in addr.protocols()]

    return PeerInfo(peer_id, peer_data)


class InvalidAddrError(ValueError):
    pass
