from typing import (
    TYPE_CHECKING,
)

from multiaddr import (
    Multiaddr,
)
import trio

from libp2p.abc import (
    INetConn,
    INetStream,
    INetwork,
    INotifee,
)

if TYPE_CHECKING:
    from libp2p.peer.id import ID  # noqa: F401


class PubsubNotifee(INotifee):
    initiator_peers_queue: "trio.MemorySendChannel[ID]"
    dead_peers_queue: "trio.MemorySendChannel[ID]"

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
        self.dead_peers_queue = dead_peers_queue

    async def opened_stream(self, network: INetwork, stream: INetStream) -> None:
        await trio.lowlevel.checkpoint()

    async def closed_stream(self, network: INetwork, stream: INetStream) -> None:
        await trio.lowlevel.checkpoint()

    async def connected(self, network: INetwork, conn: INetConn) -> None:
        """
        Add peer_id to initiator_peers_queue, so that this peer_id can be used
        to create a stream and we only want to have one pubsub stream with each
        peer.

        :param network: network the connection was opened on
        :param conn: connection that was opened
        """
        try:
            await self.initiator_peers_queue.send(conn.muxed_conn.peer_id)
        except trio.BrokenResourceError:
            # The receive channel is closed by Pubsub. We should do nothing here.
            pass

    async def disconnected(self, network: INetwork, conn: INetConn) -> None:
        """
        Add peer_id to dead_peers_queue, so that pubsub and its router can
        remove this peer_id and close the stream inbetween.

        :param network: network the connection was opened on
        :param conn: connection that was opened
        """
        try:
            await self.dead_peers_queue.send(conn.muxed_conn.peer_id)
        except trio.BrokenResourceError:
            # The receive channel is closed by Pubsub. We should do nothing here.
            pass

    async def listen(self, network: INetwork, multiaddr: Multiaddr) -> None:
        await trio.lowlevel.checkpoint()

    async def listen_close(self, network: INetwork, multiaddr: Multiaddr) -> None:
        await trio.lowlevel.checkpoint()
