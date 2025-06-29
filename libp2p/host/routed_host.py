from libp2p.abc import (
    INetworkService,
    IPeerRouting,
)
from libp2p.host.basic_host import (
    BasicHost,
)
from libp2p.host.exceptions import (
    ConnectionFailure,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)


# RoutedHost is a p2p Host that includes a routing system.
# This allows the Host to find the addresses for peers when it does not have them.
class RoutedHost(BasicHost):
    _router: IPeerRouting

    def __init__(
        self, network: INetworkService, router: IPeerRouting, enable_mDNS: bool = False
    ):
        super().__init__(network, enable_mDNS)
        self._router = router

    async def connect(self, peer_info: PeerInfo) -> None:
        """
        Ensure there is a connection between this host and the peer
        with given `peer_info.peer_id`. See (basic_host).connect for more
        information.

        RoutedHost's Connect differs in that if the host has no addresses for a
        given peer, it will use its routing system to try to find some.

        :param peer_info: peer_info of the peer we want to connect to
        :type peer_info: peer.peerinfo.PeerInfo
        """
        # check if we were given some addresses, otherwise, find some with the
        # routing system.
        if not peer_info.addrs:
            found_peer_info = await self._router.find_peer(peer_info.peer_id)
            if not found_peer_info:
                raise ConnectionFailure("Unable to find Peer address")
            self.peerstore.add_addrs(peer_info.peer_id, found_peer_info.addrs, 120)
        self.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, 120)

        # there is already a connection to this peer
        if peer_info.peer_id in self._network.connections:
            return

        await self._network.dial_peer(peer_info.peer_id)
