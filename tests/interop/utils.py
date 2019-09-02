import asyncio
from typing import Union

from multiaddr import Multiaddr

from libp2p.host.host_interface import IHost
from libp2p.peer.peerinfo import PeerInfo

from .daemon import Daemon

TDaemonOrHost = Union[IHost, Daemon]


async def connect(a: TDaemonOrHost, b: TDaemonOrHost) -> None:
    # Type check
    err_msg = (
        f"Type of type(a)={type(a)} or type(b)={type(b)} is wrong."
        "Should be either `IHost` or `Daemon`"
    )
    assert all(
        [isinstance(node, IHost) or isinstance(node, Daemon) for node in (a, b)]
    ), err_msg

    # TODO: Get peer info
    peer_info: PeerInfo
    if isinstance(b, Daemon):
        peer_info = b.peer_info
    else:  # isinstance(b, IHost)
        peer_id = b.get_id()
        maddrs = [
            b.get_addrs()[0].decapsulate(Multiaddr(f"/p2p/{peer_id.to_string()}"))
        ]
        peer_info = PeerInfo(peer_id, maddrs)
    # TODO: connect to peer info
    if isinstance(a, Daemon):
        await a.control.connect(peer_info.peer_id, peer_info.addrs)
    else:  # isinstance(b, IHost)
        await a.connect(peer_info)
    # Allow additional sleep for both side to establish the connection.
    await asyncio.sleep(0.01)
