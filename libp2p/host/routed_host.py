from libp2p.peer.peerstore import PeerStoreError

from .basic_host import BasicHost


class RoutedHost(BasicHost):

    # default options constructor
    def __init__(self, host, router):
        super().__init__(host.network)
        self.host = host
        self.router = router

    async def advertise(self, service):
        await self.router.advertise(service)

    async def connect(self, peer_info):
        """
        connect ensures there is a connection between this host and the peer with
        given peer_info.peer_id. connect will absorb the addresses in peer_info into its internal
        peerstore. If there is not an active connection, connect will issue a
        dial, and block until a connection is open, or an error is
        returned.

        :param peer_info: peer_info of the host we want to connect to
        :type peer_info: peer.peerinfo.PeerInfo
        """
        # there is already a connection to this peer
        if peer_info.peer_id in self.network.connections:
            return

        # Check if we have some address for that peer
        # if not, we use the router to get information about the peer
        peer_info.addrs = await self._find_peer_addrs(peer_info.peer_id)

        # if addrs are given, save them
        if peer_info.addrs:
            self.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, 10)

        # try to connect
        await super().connect(peer_info)

    def find_peers(self, service):
        return self.router.find_peers(service)

    async def _find_peer_addrs(self, peer_id):
        try:
            addrs = self.peerstore.addrs(peer_id)
        except PeerStoreError:
            addrs = None

        if not addrs:
            peers_info = await self.router.find_peers(peer_id.pretty())
            if not peers_info:
                raise KeyError("no address found for this peer_id %s" % str(peer_id))
            peer_info = peers_info[0]  # todo: handle multiple response
            if peer_info.peer_id != peer_id:
                raise RuntimeError('routing failure: provided addrs for different peer')
            addrs = peer_info.addrs

        return addrs
