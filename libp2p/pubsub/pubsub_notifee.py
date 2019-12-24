from typing import TYPE_CHECKING

from multiaddr import Multiaddr

from libp2p.network.connection.net_connection_interface import INetConn
from libp2p.network.network_interface import INetwork
from libp2p.network.notifee_interface import INotifee
from libp2p.network.stream.net_stream_interface import INetStream

if TYPE_CHECKING:
    import trio  # noqa: F401
    from libp2p.peer.id import ID  # noqa: F401


class PubsubNotifee(INotifee):

    initiator_peers_queue: "trio.MemorySendChannel[ID]"
    dead_peers_queue: "trio.MemorySendChannel[ID]"
    dead_peers_queue_lock: trio.Lock

    def __init__(
        self,
        initiator_peers_queue: "trio.MemorySendChannel[ID]",
        dead_peers_queue: "trio.MemorySendChannel[ID]",
    ) -> None:
        """
        :param initiator_peers_queue: queue to add new peers to so that pubsub
        can process new peers after we connect to them
        :param dead_peers_queue: queue to add dead peers to so that pubsub
        can process dead peers after we disconnect from each other
        """
        self.initiator_peers_queue = initiator_peers_queue
        self.initiator_peers_queue_lock: trio.Lock()
        self.dead_peers_queue = dead_peers_queue
        self.dead_peers_queue_lock: trio.Lock()

    async def opened_stream(self, network: INetwork, stream: INetStream) -> None:
        pass

    async def closed_stream(self, network: INetwork, stream: INetStream) -> None:
        pass

    async def connected(self, network: INetwork, conn: INetConn) -> None:
        """
        Add peer_id to initiator_peers_queue, so that this peer_id can be used
        to create a stream and we only want to have one pubsub stream with each
        peer.

        :param network: network the connection was opened on
        :param conn: connection that was opened
        """
        async with self.initiator_peers_queue_lock:
            try:
                await self.initiator_peers_queue.send(conn.muxed_conn.peer_id)
            except (
                trio.BrokenResourceError,
                trio.ClosedResourceError,
                trio.BusyResourceError,
            ):
                # Raised when the receive channel is closed.
                # TODO: Do something with loggers?
                ...

    async def disconnected(self, network: INetwork, conn: INetConn) -> None:
        """
        Add peer_id to dead_peers_queue, so that pubsub and its router can
        remove this peer_id and close the stream inbetween.

        :param network: network the connection was opened on
        :param conn: connection that was opened
        """
        async with self.dead_peers_queue_lock:
            try:
                await self.dead_peers_queue.send(conn.muxed_conn.peer_id)
            except (
                trio.BrokenResourceError,
                trio.ClosedResourceError,
                trio.BusyResourceError,
            ):
                # Raised when the receive channel is closed.
                # TODO: Do something with loggers?
                ...

    async def listen(self, network: INetwork, multiaddr: Multiaddr) -> None:
        pass

    async def listen_close(self, network: INetwork, multiaddr: Multiaddr) -> None:
        pass
