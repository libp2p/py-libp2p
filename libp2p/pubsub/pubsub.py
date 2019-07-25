# pylint: disable=no-name-in-module
import asyncio
import time
from typing import (
    Any,
    Dict,
    List,
    Sequence,
    Tuple,
)

from lru import LRU

from libp2p.host.host_interface import (
    IHost,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.network.stream.net_stream_interface import (
    INetStream,
)

from .pb import rpc_pb2
from .pubsub_notifee import PubsubNotifee
from .pubsub_router_interface import (
    IPubsubRouter,
)


def get_msg_id(msg: rpc_pb2.Message) -> Tuple[bytes, bytes]:
    # NOTE: `string(from, seqno)` in Go
    return (msg.seqno, msg.from_id)


class Pubsub:
    # pylint: disable=too-many-instance-attributes, no-member

    host: IHost
    my_id: ID
    router: IPubsubRouter
    peer_queue: asyncio.Queue
    protocols: Sequence[str]
    incoming_msgs_from_peers: asyncio.Queue()
    outgoing_messages: asyncio.Queue()
    seen_messages: LRU
    my_topics: Dict[str, asyncio.Queue]
    # FIXME: Should be changed to `Dict[str, List[ID]]`
    peer_topics: Dict[str, List[str]]
    # FIXME: Should be changed to `Dict[ID, INetStream]`
    peers: Dict[str, INetStream]
    # NOTE: Be sure it is increased atomically everytime.
    counter: int  # uint64

    def __init__(
            self,
            host: IHost,
            router: IPubsubRouter,
            my_id: ID,
            cache_size: int = None) -> None:
        """
        Construct a new Pubsub object, which is responsible for handling all
        Pubsub-related messages and relaying messages as appropriate to the
        Pubsub router (which is responsible for choosing who to send messages to).
        Since the logic for choosing peers to send pubsub messages to is
        in the router, the same Pubsub impl can back floodsub, gossipsub, etc.
        """
        self.host = host
        self.router = router
        self.my_id = my_id

        # Attach this new Pubsub object to the router
        self.router.attach(self)

        # Register a notifee
        self.peer_queue = asyncio.Queue()
        self.host.get_network().notify(PubsubNotifee(self.peer_queue))

        # Register stream handlers for each pubsub router protocol to handle
        # the pubsub streams opened on those protocols
        self.protocols = self.router.get_protocols()
        for protocol in self.protocols:
            self.host.set_stream_handler(protocol, self.stream_handler)

        # Use asyncio queues for proper context switching
        self.incoming_msgs_from_peers = asyncio.Queue()
        self.outgoing_messages = asyncio.Queue()

        # keeps track of seen messages as LRU cache
        if cache_size is None:
            self.cache_size = 128
        else:
            self.cache_size = cache_size

        self.seen_messages = LRU(self.cache_size)

        # Map of topics we are subscribed to blocking queues
        # for when the given topic receives a message
        self.my_topics = {}

        # Map of topic to peers to keep track of what peers are subscribed to
        self.peer_topics = {}

        # Create peers map, which maps peer_id (as string) to stream (to a given peer)
        self.peers = {}

        self.counter = time.time_ns()

        # Call handle peer to keep waiting for updates to peer queue
        asyncio.ensure_future(self.handle_peer_queue())

    def get_hello_packet(self) -> bytes:
        """
        Generate subscription message with all topics we are subscribed to
        only send hello packet if we have subscribed topics
        """
        packet = rpc_pb2.RPC()
        if self.my_topics:
            for topic_id in self.my_topics:
                packet.subscriptions.extend([rpc_pb2.RPC.SubOpts(
                    subscribe=True, topicid=topic_id)])

        return packet.SerializeToString()

    async def continuously_read_stream(self, stream: INetStream) -> None:
        """
        Read from input stream in an infinite loop. Process
        messages from other nodes
        :param stream: stream to continously read from
        """
        peer_id = stream.mplex_conn.peer_id

        while True:
            incoming = (await stream.read())
            rpc_incoming = rpc_pb2.RPC()
            rpc_incoming.ParseFromString(incoming)

            if rpc_incoming.publish:
                # deal with RPC.publish
                for msg in rpc_incoming.publish:
                    if not self._is_subscribed_to_msg(msg):
                        continue
                    # TODO(mhchia): This will block this read_stream loop until all data are pushed.
                    #   Should investigate further if this is an issue.
                    await self.push_msg(src=peer_id, msg=msg)

            if rpc_incoming.subscriptions:
                # deal with RPC.subscriptions
                # We don't need to relay the subscription to our
                # peers because a given node only needs its peers
                # to know that it is subscribed to the topic (doesn't
                # need everyone to know)
                for message in rpc_incoming.subscriptions:
                    self.handle_subscription(peer_id, message)

            if rpc_incoming.control:
                # Pass rpc to router so router could perform custom logic
                await self.router.handle_rpc(rpc_incoming, peer_id)

            # Force context switch
            await asyncio.sleep(0)

    async def stream_handler(self, stream: INetStream) -> None:
        """
        Stream handler for pubsub. Gets invoked whenever a new stream is created
        on one of the supported pubsub protocols.
        :param stream: newly created stream
        """
        # Add peer
        # Map peer to stream
        peer_id = stream.mplex_conn.peer_id
        self.peers[str(peer_id)] = stream
        self.router.add_peer(peer_id, stream.get_protocol())

        # Send hello packet
        hello = self.get_hello_packet()

        await stream.write(hello)
        # Pass stream off to stream reader
        asyncio.ensure_future(self.continuously_read_stream(stream))

    async def handle_peer_queue(self) -> None:
        """
        Continuously read from peer queue and each time a new peer is found,
        open a stream to the peer using a supported pubsub protocol
        TODO: Handle failure for when the peer does not support any of the
        pubsub protocols we support
        """
        while True:

            peer_id = await self.peer_queue.get()

            # Open a stream to peer on existing connection
            # (we know connection exists since that's the only way
            # an element gets added to peer_queue)
            stream = await self.host.new_stream(peer_id, self.protocols)

            # Add Peer
            # Map peer to stream
            self.peers[str(peer_id)] = stream
            self.router.add_peer(peer_id, stream.get_protocol())

            # Send hello packet
            hello = self.get_hello_packet()
            await stream.write(hello)

            # Pass stream off to stream reader
            asyncio.ensure_future(self.continuously_read_stream(stream))

            # Force context switch
            await asyncio.sleep(0)

    # FIXME: `sub_message` can be further type hinted with mypy_protobuf
    def handle_subscription(self, origin_id: ID, sub_message: Any) -> None:
        """
        Handle an incoming subscription message from a peer. Update internal
        mapping to mark the peer as subscribed or unsubscribed to topics as
        defined in the subscription message
        :param origin_id: id of the peer who subscribe to the message
        :param sub_message: RPC.SubOpts
        """
        origin_id = str(origin_id)
        if sub_message.subscribe:
            if sub_message.topicid not in self.peer_topics:
                self.peer_topics[sub_message.topicid] = [origin_id]
            elif origin_id not in self.peer_topics[sub_message.topicid]:
                # Add peer to topic
                self.peer_topics[sub_message.topicid].append(origin_id)
        else:
            if sub_message.topicid in self.peer_topics:
                if origin_id in self.peer_topics[sub_message.topicid]:
                    self.peer_topics[sub_message.topicid].remove(origin_id)

    # FIXME(mhchia): Change the function name?
    # FIXME(mhchia): `publish_message` can be further type hinted with mypy_protobuf
    async def handle_talk(self, publish_message: Any) -> None:
        """
        Put incoming message from a peer onto my blocking queue
        :param talk: RPC.Message format
        """

        # Check if this message has any topics that we are subscribed to
        for topic in publish_message.topicIDs:
            if topic in self.my_topics:
                # we are subscribed to a topic this message was sent for,
                # so add message to the subscription output queue
                # for each topic
                await self.my_topics[topic].put(publish_message)

    async def subscribe(self, topic_id: str) -> asyncio.Queue:
        """
        Subscribe ourself to a topic
        :param topic_id: topic_id to subscribe to
        """

        # Already subscribed
        if topic_id in self.my_topics:
            return self.my_topics[topic_id]

        # Map topic_id to blocking queue
        self.my_topics[topic_id] = asyncio.Queue()

        # Create subscribe message
        packet = rpc_pb2.RPC()
        packet.subscriptions.extend([rpc_pb2.RPC.SubOpts(
            subscribe=True,
            topicid=topic_id.encode('utf-8')
            )])

        # Send out subscribe message to all peers
        await self.message_all_peers(packet.SerializeToString())

        # Tell router we are joining this topic
        await self.router.join(topic_id)

        # Return the asyncio queue for messages on this topic
        return self.my_topics[topic_id]

    async def unsubscribe(self, topic_id: str) -> None:
        """
        Unsubscribe ourself from a topic
        :param topic_id: topic_id to unsubscribe from
        """

        # Return if we already unsubscribed from the topic
        if topic_id not in self.my_topics:
            return
        # Remove topic_id from map if present
        del self.my_topics[topic_id]

        # Create unsubscribe message
        packet = rpc_pb2.RPC()
        packet.subscriptions.extend([rpc_pb2.RPC.SubOpts(
            subscribe=False,
            topicid=topic_id.encode('utf-8')
            )])

        # Send out unsubscribe message to all peers
        await self.message_all_peers(packet.SerializeToString())

        # Tell router we are leaving this topic
        await self.router.leave(topic_id)

    # FIXME: `rpc_msg` can be further type hinted with mypy_protobuf
    async def message_all_peers(self, rpc_msg: Any) -> None:
        """
        Broadcast a message to peers
        :param raw_msg: raw contents of the message to broadcast
        """

        # Broadcast message
        for _, stream in self.peers.items():
            # Write message to stream
            await stream.write(rpc_msg)

    def list_peers(self, topic_id: str) -> Tuple[ID, ...]:
        return

    async def publish(self, topic_id: str, data: bytes) -> None:
        """
        Publish data to a topic
        :param topic_id: topic which we are going to publish the data to
        :param data: data which we are publishing
        """
        msg = rpc_pb2.Message(
            data=data,
            topicIDs=[topic_id],
            # Origin is myself.
            from_id=self.host.get_id().to_bytes(),
            seqno=self._next_seqno(),
        )

        # TODO: Sign with our signing key

        await self.push_msg(self.host.get_id(), msg)

    async def push_msg(self, src: ID, msg: rpc_pb2.Message) -> None:
        """
        Push a pubsub message to others.
        :param src: the peer who forward us the message.
        :param msg: the message we are going to push out.
        """
        # TODO: - Check if the `source` is in the blacklist. If yes, reject.

        # TODO: - Check if the `from` is in the blacklist. If yes, reject.

        # TODO: - Check if signing is required and if so signature should be attached.

        if self._is_msg_seen(msg):
            return

        # TODO: - Validate the message. If failed, reject it.

        self._mark_msg_seen(msg)
        await self.handle_talk(msg)
        await self.router.publish(src, msg)

    def _next_seqno(self) -> bytes:
        """
        Make the next message sequence id.
        """
        self.counter += 1
        return self.counter.to_bytes(8, 'big')

    def _is_msg_seen(self, msg: rpc_pb2.Message) -> bool:
        msg_id = get_msg_id(msg)
        return msg_id in self.seen_messages

    def _mark_msg_seen(self, msg: rpc_pb2.Message) -> None:
        msg_id = get_msg_id(msg)
        # FIXME: Mapping `msg_id` to `1` is quite awkward. Should investigate if there is a
        #   more appropriate way.
        self.seen_messages[msg_id] = 1

    def _is_subscribed_to_msg(self, msg: rpc_pb2.Message) -> bool:
        if len(self.my_topics) == 0:
            return False
        return all([topic in self.my_topics for topic in msg.topicIDs])
