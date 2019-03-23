from libp2p.network.notifee_interface import INotifee


class PubsubNotifee(INotifee):
    # pylint: disable=too-many-instance-attributes, cell-var-from-loop

    def __init__(self, initiator_peers_queue):
        """
        :param initiator_peers_queue: queue to add new peers to so that pubsub
        can process new peers after we connect to them
        """
        self.initiator_peers_queue = initiator_peers_queue

    async def opened_stream(self, network, stream):
        pass

    async def closed_stream(self, network, stream):
        pass

    async def connected(self, network, conn):
        """
        Add peer_id to initiator_peers_queue, so that this peer_id can be used to
        create a stream and we only want to have one pubsub stream with each peer.
        :param network: network the connection was opened on
        :param conn: connection that was opened
        """

        # Only add peer_id if we are initiator (otherwise we would end up
        # with two pubsub streams between us and the peer)
        if conn.initiator:
            await self.initiator_peers_queue.put(conn.peer_id)

    async def disconnected(self, network, conn):
        pass

    async def listen(self, network, multiaddr):
        pass

    async def listen_close(self, network, multiaddr):
        pass
