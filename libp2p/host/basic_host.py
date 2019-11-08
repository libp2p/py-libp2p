import logging
from typing import TYPE_CHECKING, List, Sequence

import multiaddr

from libp2p.crypto.keys import PublicKey
from libp2p.host.defaults import get_default_protocols
from libp2p.host.exceptions import StreamFailure
from libp2p.network.network_interface import INetwork
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.peerstore_interface import IPeerStore
from libp2p.protocol_muxer.exceptions import MultiselectClientError, MultiselectError
from libp2p.protocol_muxer.multiselect import Multiselect
from libp2p.protocol_muxer.multiselect_client import MultiselectClient
from libp2p.protocol_muxer.multiselect_communicator import MultiselectCommunicator
from libp2p.typing import StreamHandlerFn, TProtocol

from .host_interface import IHost

if TYPE_CHECKING:
    from collections import OrderedDict

# Upon host creation, host takes in options,
# including the list of addresses on which to listen.
# Host then parses these options and delegates to its Network instance,
# telling it to listen on the given listen addresses.


logger = logging.getLogger("libp2p.network.basic_host")


class BasicHost(IHost):
    """
    BasicHost is a wrapper of a `INetwork` implementation.

    It performs protocol negotiation on a stream with multistream-select
    right after a stream is initialized.
    """

    _public_key: PublicKey
    _network: INetwork
    peerstore: IPeerStore

    multiselect: Multiselect
    multiselect_client: MultiselectClient

    def __init__(
        self,
        public_key: PublicKey,
        network: INetwork,
        default_protocols: "OrderedDict[TProtocol, StreamHandlerFn]" = None,
    ) -> None:
        self._public_key = public_key
        self._network = network
        self._network.set_stream_handler(self._swarm_stream_handler)
        self.peerstore = self._network.peerstore
        # Protocol muxing
        default_protocols = default_protocols or get_default_protocols(self)
        self.multiselect = Multiselect(default_protocols)
        self.multiselect_client = MultiselectClient()

    def get_id(self) -> ID:
        """
        :return: peer_id of host
        """
        return self._network.get_peer_id()

    def get_public_key(self) -> PublicKey:
        return self._public_key

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

    def get_mux(self) -> Multiselect:
        """
        :return: mux instance of host
        """
        return self.multiselect

    def get_addrs(self) -> List[multiaddr.Multiaddr]:
        """
        :return: all the multiaddr addresses this host is listening to
        """
        # TODO: We don't need "/p2p/{peer_id}" postfix actually.
        p2p_part = multiaddr.Multiaddr("/p2p/{}".format(self.get_id().pretty()))

        addrs: List[multiaddr.Multiaddr] = []
        for transport in self._network.listeners.values():
            for addr in transport.get_addrs():
                addrs.append(addr.encapsulate(p2p_part))
        return addrs

    def set_stream_handler(
        self, protocol_id: TProtocol, stream_handler: StreamHandlerFn
    ) -> None:
        """
        set stream handler for given `protocol_id`

        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler function
        """
        self.multiselect.add_handler(protocol_id, stream_handler)

    async def new_stream(
        self, peer_id: ID, protocol_ids: Sequence[TProtocol]
    ) -> INetStream:
        """
        :param peer_id: peer_id that host is connecting
        :param protocol_ids: available protocol ids to use for stream
        :return: stream: new stream created
        """

        net_stream = await self._network.new_stream(peer_id)

        # Perform protocol muxing to determine protocol to use
        try:
            selected_protocol = await self.multiselect_client.select_one_of(
                list(protocol_ids), MultiselectCommunicator(net_stream)
            )
        except MultiselectClientError as error:
            logger.debug("fail to open a stream to peer %s, error=%s", peer_id, error)
            await net_stream.reset()
            raise StreamFailure("failt to open a stream to peer %s", peer_id) from error

        net_stream.set_protocol(selected_protocol)
        return net_stream

    async def connect(self, peer_info: PeerInfo) -> None:
        """
        connect ensures there is a connection between this host and the peer
        with given `peer_info.peer_id`. connect will absorb the addresses in
        peer_info into its internal peerstore. If there is not an active
        connection, connect will issue a dial, and block until a connection is
        opened, or an error is returned.

        :param peer_info: peer_info of the peer we want to connect to
        :type peer_info: peer.peerinfo.PeerInfo
        """
        self.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, 10)

        # there is already a connection to this peer
        if peer_info.peer_id in self._network.connections:
            return

        await self._network.dial_peer(peer_info.peer_id)

    async def disconnect(self, peer_id: ID) -> None:
        await self._network.close_peer(peer_id)

    async def close(self) -> None:
        await self._network.close()

    # Reference: `BasicHost.newStreamHandler` in Go.
    async def _swarm_stream_handler(self, net_stream: INetStream) -> None:
        # Perform protocol muxing to determine protocol to use
        try:
            protocol, handler = await self.multiselect.negotiate(
                MultiselectCommunicator(net_stream)
            )
        except MultiselectError as error:
            peer_id = net_stream.muxed_conn.peer_id
            logger.debug(
                "failed to accept a stream from peer %s, error=%s", peer_id, error
            )
            await net_stream.reset()
            return
        net_stream.set_protocol(protocol)
        await handler(net_stream)
