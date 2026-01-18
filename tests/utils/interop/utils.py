from typing import (
    Union,
)

from multiaddr import (
    Multiaddr,
)
from p2pclient.libp2p_stubs.peer.id import ID as StubID
import trio

from libp2p.abc import IHost
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)

from .daemon import (
    Daemon,
)

TDaemonOrHost = Union[IHost, Daemon]


def _get_peer_info(node: TDaemonOrHost) -> PeerInfo:
    peer_info: PeerInfo
    if isinstance(node, Daemon):
        peer_info = node.peer_info
    else:  # isinstance(node, IHost)
        peer_id = node.get_id()
        maddrs = [
            node.get_addrs()[0].decapsulate(Multiaddr(f"/p2p/{peer_id.to_string()}"))
        ]
        peer_info = PeerInfo(peer_id, maddrs)
    return peer_info


async def _is_peer(peer_id: ID, node: TDaemonOrHost) -> bool:
    if isinstance(node, Daemon):
        pinfos = await node.control.list_peers()
        peers = tuple([pinfo.peer_id for pinfo in pinfos])
        return peer_id in peers
    else:  # isinstance(node, IHost)
        return peer_id in node.get_network().connections


async def connect(a: TDaemonOrHost, b: TDaemonOrHost) -> None:
    # Type check
    err_msg = (
        f"Type of a={type(a)} or type of b={type(b)} is wrong."
        "Should be either `IHost` or `Daemon`"
    )
    assert all(
        [isinstance(node, IHost) or isinstance(node, Daemon) for node in (a, b)]
    ), err_msg

    b_peer_info = _get_peer_info(b)
    if isinstance(a, Daemon):
        # Convert internal libp2p ID to p2pclient stub ID .connect()
        await a.control.connect(
            StubID(b_peer_info.peer_id.to_bytes()), b_peer_info.addrs
        )
    else:  # isinstance(b, IHost)
        await a.connect(b_peer_info)
    # Allow additional sleep for both side to establish the connection.
    await trio.sleep(0.1)

    a_peer_info = _get_peer_info(a)

    assert await _is_peer(b_peer_info.peer_id, a)
    assert await _is_peer(a_peer_info.peer_id, b)
