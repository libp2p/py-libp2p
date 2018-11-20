from peer.id import id_b58_decode
from peer.peerdata import PeerData
import multiaddr
import multiaddr.util

class PeerInfo:
	# pylint: disable=too-few-public-methods
    def __init__(self, peer_id, peer_data):
        self.peer_id = peer_id
        self.addrs = peer_data.get_addrs()


def info_from_p2p_addr(m):
    if not m:
        raise InvalidAddrError()

    parts = multiaddr.util.split(m)
    if len(parts) < 1:
        raise InvalidAddrError()

    ipfspart = parts[-1]
    if ipfspart.protocols()[0].code != multiaddr.protocols.P_IPFS:
        raise InvalidAddrError()

    # make sure the /ipfs value parses as a peer.ID
    peerIdParts = str(ipfspart).split('/')
    peerIdStr = ipfspart.value_for_protocol(multiaddr.protocols.P_IPFS)
    id = id_b58_decode(peerIdStr)

    # we might have received just an / ipfs part, which means there's no addr.
    if len(parts) > 1:
        addr = multiaddr.util.join(parts[:-1])

    peer_data = PeerData()
    peer_data.addrs = [addr]
    peer_data.protocols = [p.code for p in addr.protocols()]

    return PeerInfo(id, peer_data)


class InvalidAddrError(ValueError):
    pass
