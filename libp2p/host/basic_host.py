from __future__ import annotations

from collections.abc import (
    AsyncIterator,
    Sequence,
)
from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
)
import logging
from typing import (
    TYPE_CHECKING,
)

import multiaddr

from libp2p.abc import (
    IHost,
    IMuxedConn,
    INetConn,
    INetStream,
    INetworkService,
    IPeerStore,
    IRawConnection,
)
from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)
from libp2p.custom_types import (
    StreamHandlerFn,
    TProtocol,
)
from libp2p.discovery.bootstrap.bootstrap import BootstrapDiscovery
from libp2p.discovery.mdns.mdns import MDNSDiscovery
from libp2p.discovery.upnp.upnp import UpnpManager
from libp2p.host.defaults import (
    get_default_protocols,
)
from libp2p.host.exceptions import (
    StreamFailure,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.peer.peerstore import create_signed_peer_record
from libp2p.protocol_muxer.exceptions import (
    MultiselectClientError,
    MultiselectError,
)
from libp2p.protocol_muxer.multiselect import (
    Multiselect,
)
from libp2p.protocol_muxer.multiselect_client import (
    MultiselectClient,
)
from libp2p.protocol_muxer.multiselect_communicator import (
    MultiselectCommunicator,
)
from libp2p.rcmgr import ResourceManager
from libp2p.tools.async_service import (
    background_trio_service,
)

if TYPE_CHECKING:
    from collections import (
        OrderedDict,
    )
from multiaddr import Multiaddr

# Upon host creation, host takes in options,
# including the list of addresses on which to listen.
# Host then parses these options and delegates to its Network instance,
# telling it to listen on the given listen addresses.


logger = logging.getLogger("libp2p.network.basic_host")
DEFAULT_NEGOTIATE_TIMEOUT = 5


class BasicHost(IHost):
    """
    BasicHost is a wrapper of a `INetwork` implementation.

    It performs protocol negotiation on a stream with multistream-select
    right after a stream is initialized.
    """

    _network: INetworkService
    peerstore: IPeerStore

    multiselect: Multiselect
    multiselect_client: MultiselectClient
    mDNS: MDNSDiscovery | None
    upnp: UpnpManager | None
    bootstrap: BootstrapDiscovery | None

    def __init__(
        self,
        network: INetworkService,
        enable_mDNS: bool = False,
        enable_upnp: bool = False,
        bootstrap: list[str] | None = None,
        default_protocols: OrderedDict[TProtocol, StreamHandlerFn] | None = None,
        negotiate_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
        resource_manager: ResourceManager | None = None,
    ) -> None:
        """
        Initialize a BasicHost instance.

        :param network: Network service implementation
        :param enable_mDNS: Enable mDNS discovery
        :param enable_upnp: Enable UPnP port mapping
        :param bootstrap: Bootstrap peer addresses
        :param default_protocols: Default protocol handlers
        :param negotiate_timeout: Protocol negotiation timeout
        :param resource_manager: Optional resource manager instance
        :type resource_manager: :class:`libp2p.rcmgr.ResourceManager` or None
        """
        self._network = network
        self._network.set_stream_handler(self._swarm_stream_handler)
        self.peerstore = self._network.peerstore
        self.negotiate_timeout = negotiate_timeout

        # Set up resource manager if provided
        if resource_manager is not None:
            if hasattr(self._network, "set_resource_manager"):
                self._network.set_resource_manager(resource_manager)  # type: ignore
            else:
                # Log warning if network doesn't support resource manager
                logger.warning(
                    "Resource manager provided but network service doesn't support it"
                )
        # Protocol muxing
        default_protocols = default_protocols or get_default_protocols(self)
        self.multiselect = Multiselect(dict(default_protocols.items()))
        self.multiselect_client = MultiselectClient()
        self.mDNS = None
        if enable_mDNS:
            self.mDNS = MDNSDiscovery(network)

        # Initialize bootstrap discovery container. Keep attribute defined so
        # we can avoid hasattr checks elsewhere.
        self.bootstrap = None
        if bootstrap:
            self.bootstrap = BootstrapDiscovery(network, bootstrap)

        # Cache a signed-record if the local-node in the PeerStore
        envelope = create_signed_peer_record(
            self.get_id(),
            self.get_addrs(),
            self.get_private_key(),
        )
        self.get_peerstore().set_local_record(envelope)

        # Initialize UPnP manager if enabled
        # Note: UPnP integration follows the same pattern as mDNS for consistency.
        # The UpnpManager is a standalone component that can be used independently
        # or integrated into the host lifecycle for automatic port management.
        self.upnp = None
        if enable_upnp:
            self.upnp = UpnpManager()

    def get_id(self) -> ID:
        """
        :return: peer_id of host
        """
        return self._network.get_peer_id()

    def get_public_key(self) -> PublicKey:
        return self.peerstore.pubkey(self.get_id())

    def get_private_key(self) -> PrivateKey:
        return self.peerstore.privkey(self.get_id())

    def get_network(self) -> INetworkService:
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

    def get_addrs(self) -> list[multiaddr.Multiaddr]:
        """
        :return: all the multiaddr addresses this host is listening to
        """
        # TODO: We don't need "/p2p/{peer_id}" postfix actually.
        p2p_part = multiaddr.Multiaddr(f"/p2p/{self.get_id()!s}")

        addrs: list[multiaddr.Multiaddr] = []
        for transport in self._network.listeners.values():
            for addr in transport.get_addrs():
                addrs.append(addr.encapsulate(p2p_part))
        return addrs

    def get_connected_peers(self) -> list[ID]:
        """
        :return: all the ids of peers this host is currently connected to
        """
        return list(self._network.connections.keys())

    def run(
        self, listen_addrs: Sequence[multiaddr.Multiaddr]
    ) -> AbstractAsyncContextManager[None]:
        """
        Run the host instance and listen to ``listen_addrs``.

        :param listen_addrs: a sequence of multiaddrs that we want to listen to
        """

        @asynccontextmanager
        async def _run() -> AsyncIterator[None]:
            network = self.get_network()
            async with background_trio_service(network):
                await network.listen(*listen_addrs)
                if self.mDNS is not None:
                    logger.debug("Starting mDNS Discovery")
                    self.mDNS.start()
                if self.upnp is not None:
                    upnp_manager = self.upnp
                    logger.debug("Starting UPnP discovery and port mapping")
                    if await upnp_manager.discover():
                        for addr in self.get_addrs():
                            if port := addr.value_for_protocol("tcp"):
                                await upnp_manager.add_port_mapping(port, "TCP")
                if self.bootstrap is not None:
                    logger.debug("Starting Bootstrap Discovery")
                    await self.bootstrap.start()

                try:
                    yield
                finally:
                    if self.mDNS is not None:
                        self.mDNS.stop()
                    if self.upnp and self.upnp.get_external_ip():
                        upnp_manager = self.upnp
                        logger.debug("Removing UPnP port mappings")
                        for addr in self.get_addrs():
                            if port := addr.value_for_protocol("tcp"):
                                await upnp_manager.remove_port_mapping(port, "TCP")
                    if self.bootstrap is not None:
                        self.bootstrap.stop()

        return _run()

    def set_stream_handler(
        self, protocol_id: TProtocol, stream_handler: StreamHandlerFn
    ) -> None:
        """
        Set stream handler for given `protocol_id`

        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler function
        """
        self.multiselect.add_handler(protocol_id, stream_handler)

    async def new_stream(
        self,
        peer_id: ID,
        protocol_ids: Sequence[TProtocol],
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
                list(protocol_ids),
                MultiselectCommunicator(net_stream),
                self.negotiate_timeout,
            )
        except MultiselectClientError as error:
            logger.debug("fail to open a stream to peer %s, error=%s", peer_id, error)
            await net_stream.reset()
            raise StreamFailure(f"failed to open a stream to peer {peer_id}") from error

        net_stream.set_protocol(selected_protocol)
        return net_stream

    async def send_command(
        self,
        peer_id: ID,
        command: str,
        response_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
    ) -> list[str]:
        """
        Send a multistream-select command to the specified peer and return
        the response.

        :param peer_id: peer_id that host is connecting
        :param command: supported multistream-select command (e.g., "ls)
        :raise StreamFailure: If the stream cannot be opened or negotiation fails
        :return: list of strings representing the response from peer.
        """
        new_stream = await self._network.new_stream(peer_id)

        try:
            response = await self.multiselect_client.query_multistream_command(
                MultiselectCommunicator(new_stream), command, response_timeout
            )
        except MultiselectClientError as error:
            logger.debug("fail to open a stream to peer %s, error=%s", peer_id, error)
            await new_stream.reset()
            raise StreamFailure(f"failed to open a stream to peer {peer_id}") from error

        return response

    async def connect(self, peer_info: PeerInfo) -> None:
        """
        Ensure there is a connection between this host and the peer
        with given `peer_info.peer_id`. connect will absorb the addresses in
        peer_info into its internal peerstore. If there is not an active
        connection, connect will issue a dial, and block until a connection is
        opened, or an error is returned.

        :param peer_info: peer_info of the peer we want to connect to
        :type peer_info: peer.peerinfo.PeerInfo
        """
        self.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, 120)

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
                MultiselectCommunicator(net_stream), self.negotiate_timeout
            )
            if protocol is None:
                await net_stream.reset()
                raise StreamFailure(
                    "Failed to negotiate protocol: no protocol selected"
                )
        except MultiselectError as error:
            peer_id = net_stream.muxed_conn.peer_id
            logger.debug(
                "failed to accept a stream from peer %s, error=%s", peer_id, error
            )
            await net_stream.reset()
            return
        if protocol is None:
            logger.debug(
                "no protocol negotiated, closing stream from peer %s",
                net_stream.muxed_conn.peer_id,
            )
            await net_stream.reset()
            return
        net_stream.set_protocol(protocol)
        if handler is None:
            logger.debug(
                "no handler for protocol %s, closing stream from peer %s",
                protocol,
                net_stream.muxed_conn.peer_id,
            )
            await net_stream.reset()
            return

        await handler(net_stream)

    def get_live_peers(self) -> list[ID]:
        """
        Returns a list of currently connected peer IDs.

        :return: List of peer IDs that have active connections
        """
        return list(self._network.connections.keys())

    def is_peer_connected(self, peer_id: ID) -> bool:
        """
        Check if a specific peer is currently connected.

        :param peer_id: ID of the peer to check
        :return: True if peer has an active connection, False otherwise
        """
        return len(self._network.get_connections(peer_id)) > 0

    def get_peer_connection_info(self, peer_id: ID) -> list[INetConn] | None:
        """
        Get connection information for a specific peer if connected.

        :param peer_id: ID of the peer to get info for
        :return: Connection object if peer is connected, None otherwise
        """
        return self._network.connections.get(peer_id)

    async def upgrade_outbound_connection(
        self, raw_conn: IRawConnection, peer_id: ID
    ) -> INetConn:
        """
        Upgrade a raw outbound connection for the peer_id using the underlying network.

        :param raw_conn: The raw connection to upgrade.
        :param peer_id: The peer this connection is to.
        :raises SwarmException: raised when security or muxer upgrade fails
        :return: network connection with security and multiplexing established
        """
        return await self._network.upgrade_outbound_raw_conn(raw_conn, peer_id)

    async def upgrade_inbound_connection(
        self, raw_conn: IRawConnection, maddr: Multiaddr
    ) -> IMuxedConn:
        """
        Upgrade a raw inbound connection using the underlying network.

        :param raw_conn: The inbound raw connection to upgrade.
        :param maddr: The multiaddress this connection arrived on.
        :raises SwarmException: raised when security or muxer upgrade fails
        :return: network connection with security and multiplexing established
        """
        return await self._network.upgrade_inbound_raw_conn(raw_conn, maddr)
