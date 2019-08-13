from typing import Any, List, Sequence

import multiaddr

from libp2p.network.network_interface import INetwork
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.peerstore_interface import IPeerStore
from libp2p.routing.kademlia.kademlia_peer_router import KadmeliaPeerRouter
from libp2p.typing import StreamHandlerFn, TProtocol

from .host_interface import IHost

# Upon host creation, host takes in options,
# including the list of addresses on which to listen.
# Host then parses these options and delegates to its Network instance,
# telling it to listen on the given listen addresses.


class BasicHost(IHost):

    _network: INetwork
    router: KadmeliaPeerRouter
    peerstore: IPeerStore

    # default options constructor
    def __init__(self, network: INetwork, router: KadmeliaPeerRouter = None) -> None:
        self._network = network
        self._router = router
        self.peerstore = self._network.peerstore

    def get_id(self) -> ID:
        """
        :return: peer_id of host
        """
        return self._network.get_peer_id()

    def get_network(self) -> INetwork:
        """
        :return: network instance of host
        """
        return self._network

    def get_peerstore(self) -> IPeerStore:
        """
        :return: peerstore of the host (same one as in its network instance)
        """
        return self.peerstore

    # FIXME: Replace with correct return type
    def get_mux(self) -> Any:
        """
        :return: mux instance of host
        """

    def get_addrs(self) -> List[multiaddr.Multiaddr]:
        """
        :return: all the multiaddr addresses this host is listening too
        """
        p2p_part = multiaddr.Multiaddr("/p2p/{}".format(self.get_id().pretty()))

        addrs: List[multiaddr.Multiaddr] = []
        for transport in self._network.listeners.values():
            for addr in transport.get_addrs():
                addrs.append(addr.encapsulate(p2p_part))
        return addrs

    def set_stream_handler(
        self, protocol_id: TProtocol, stream_handler: StreamHandlerFn
    ) -> bool:
        """
        set stream handler for host
        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler function
        :return: true if successful
        """
        return self._network.set_stream_handler(protocol_id, stream_handler)

    # protocol_id can be a list of protocol_ids
    # stream will decide which protocol_id to run on
    async def new_stream(
        self, peer_id: ID, protocol_ids: Sequence[TProtocol]
    ) -> INetStream:
        """
        :param peer_id: peer_id that host is connecting
        :param protocol_id: protocol id that stream runs on
        :return: stream: new stream created
        """
        return await self._network.new_stream(peer_id, protocol_ids)

    async def connect(self, peer_info: PeerInfo) -> None:
        """
        connect ensures there is a connection between this host and the peer with
        given peer_info.peer_id. connect will absorb the addresses in peer_info into its internal
        peerstore. If there is not an active connection, connect will issue a
        dial, and block until a connection is open, or an error is
        returned.

        :param peer_info: peer_info of the host we want to connect to
        :type peer_info: peer.peerinfo.PeerInfo
        """
        self.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, 10)

        # there is already a connection to this peer
        if peer_info.peer_id in self._network.connections:
            return

        await self._network.dial_peer(peer_info.peer_id)
