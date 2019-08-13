import asyncio
import logging
import time
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    NamedTuple,
    Tuple,
    Union,
    cast,
)

from lru import LRU

from libp2p.exceptions import ValidationError
from libp2p.host.host_interface import IHost
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.peer.id import ID
from libp2p.typing import TProtocol

from .pb import rpc_pb2
from .pubsub_notifee import PubsubNotifee
from .validators import signature_validator

if TYPE_CHECKING:
    from .pubsub_router_interface import IPubsubRouter  # noqa: F401


log = logging.getLogger(__name__)


def get_msg_id(msg: rpc_pb2.Message) -> Tuple[bytes, bytes]:
    # NOTE: `string(from, seqno)` in Go
    return (msg.seqno, msg.from_id)


SyncValidatorFn = Callable[[ID, rpc_pb2.Message], bool]
AsyncValidatorFn = Callable[[ID, rpc_pb2.Message], Awaitable[bool]]
ValidatorFn = Union[SyncValidatorFn, AsyncValidatorFn]


class TopicValidator(NamedTuple):
    validator: ValidatorFn
    is_async: bool


class Pubsub:

    host: IHost
    my_id: ID

    router: "IPubsubRouter"

    peer_queue: "asyncio.Queue[ID]"

    protocols: List[TProtocol]

    incoming_msgs_from_peers: "asyncio.Queue[rpc_pb2.Message]"
    outgoing_messages: "asyncio.Queue[rpc_pb2.Message]"

    seen_messages: LRU

    my_topics: Dict[str, "asyncio.Queue[rpc_pb2.Message]"]

    peer_topics: Dict[str, List[ID]]
    peers: Dict[ID, INetStream]

    topic_validators: Dict[str, TopicValidator]

    # NOTE: Be sure it is increased atomically everytime.
    counter: int  # uint64

    def __init__(
        self, host: IHost, router: "IPubsubRouter", my_id: ID, cache_size: int = None
    ) -> None:
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

        # Map of topic to topic validator
        self.topic_validators = {}

        self.counter = time.time_ns()

        # Call handle peer to keep waiting for updates to peer queue
        asyncio.ensure_future(self.handle_peer_queue())

    def get_hello_packet(self) -> bytes:
        """
        Generate subscription message with all topics we are subscribed to
        only send hello packet if we have subscribed topics
        """
        packet = rpc_pb2.RPC()
        for topic_id in self.my_topics:
            packet.subscriptions.extend(
                [rpc_pb2.RPC.SubOpts(subscribe=True, topicid=topic_id)]
            )
        return packet.SerializeToString()

    async def continuously_read_stream(self, stream: INetStream) -> None:
        """
        Read from input stream in an infinite loop. Process
        messages from other nodes
        :param stream: stream to continously read from
        """
        peer_id = stream.mplex_conn.peer_id

        while True:
            incoming: bytes = (await stream.read())
            rpc_incoming: rpc_pb2.RPC = rpc_pb2.RPC()
            rpc_incoming.ParseFromString(incoming)

            if rpc_incoming.publish:
                # deal with RPC.publish
                for msg in rpc_incoming.publish:
                    if not self._is_subscribed_to_msg(msg):
                        continue
                    # TODO(mhchia): This will block this read_stream loop until all data are pushed.
                    #   Should investigate further if this is an issue.
                    asyncio.ensure_future(self.push_msg(msg_forwarder=peer_id, msg=msg))

            if rpc_incoming.subscriptions:
                # deal with RPC.subscriptions
                # We don't need to relay the subscription to our
                # peers because a given node only needs its peers
                # to know that it is subscribed to the topic (doesn't
                # need everyone to know)
                for message in rpc_incoming.subscriptions:
                    self.handle_subscription(peer_id, message)

            # NOTE: Check if `rpc_incoming.control` is set through `HasField`.
            #   This is necessary because `control` is an optional field in pb2.
            #   Ref: https://developers.google.com/protocol-buffers/docs/reference/python-generated#singular-fields-proto2  # noqa: E501
            if rpc_incoming.HasField("control"):
                # Pass rpc to router so router could perform custom logic
                await self.router.handle_rpc(rpc_incoming, peer_id)

            # Force context switch
            await asyncio.sleep(0)

    def set_topic_validator(
        self, topic: str, validator: ValidatorFn, is_async_validator: bool
    ) -> None:
        """
        Register a validator under the given topic. One topic can only have one validtor.
        :param topic: the topic to register validator under
        :param validator: the validator used to validate messages published to the topic
        :param is_async_validator: indicate if the validator is an asynchronous validator
        """
        self.topic_validators[topic] = TopicValidator(validator, is_async_validator)

    def remove_topic_validator(self, topic: str) -> None:
        """
        Remove the validator from the given topic.
        :param topic: the topic to remove validator from
        """
        if topic in self.topic_validators:
            del self.topic_validators[topic]

    def get_msg_validators(self, msg: rpc_pb2.Message) -> Tuple[TopicValidator, ...]:
        """
        Get all validators corresponding to the topics in the message.
        :param msg: the message published to the topic
        """
        return tuple(
            self.topic_validators[topic]
            for topic in msg.topicIDs
            if topic in self.topic_validators
        )

    async def stream_handler(self, stream: INetStream) -> None:
        """
        Stream handler for pubsub. Gets invoked whenever a new stream is created
        on one of the supported pubsub protocols.
        :param stream: newly created stream
        """
        # Add peer
        # Map peer to stream
        peer_id: ID = stream.mplex_conn.peer_id
        self.peers[peer_id] = stream
        self.router.add_peer(peer_id, stream.get_protocol())

        # Send hello packet
        hello: bytes = self.get_hello_packet()

        await stream.write(hello)
        # Pass stream off to stream reader
        asyncio.ensure_future(self.continuously_read_stream(stream))
        # Force context switch
        await asyncio.sleep(0)

    async def handle_peer_queue(self) -> None:
        """
        Continuously read from peer queue and each time a new peer is found,
        open a stream to the peer using a supported pubsub protocol
        TODO: Handle failure for when the peer does not support any of the
        pubsub protocols we support
        """
        while True:

            peer_id: ID = await self.peer_queue.get()

            # Open a stream to peer on existing connection
            # (we know connection exists since that's the only way
            # an element gets added to peer_queue)
            stream: INetStream = await self.host.new_stream(peer_id, self.protocols)

            # Add Peer
            # Map peer to stream
            self.peers[peer_id] = stream
            self.router.add_peer(peer_id, stream.get_protocol())

            # Send hello packet
            hello: bytes = self.get_hello_packet()
            await stream.write(hello)

            # TODO: Investigate whether this should be replaced by `handlePeerEOF`
            #   Ref: https://github.com/libp2p/go-libp2p-pubsub/blob/49274b0e8aecdf6cad59d768e5702ff00aa48488/comm.go#L80  # noqa: E501
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
        :param publish_message: RPC.Message format
        """

        # Check if this message has any topics that we are subscribed to
        for topic in publish_message.topicIDs:
            if topic in self.my_topics:
                # we are subscribed to a topic this message was sent for,
                # so add message to the subscription output queue
                # for each topic
                await self.my_topics[topic].put(publish_message)

    async def subscribe(self, topic_id: str) -> "asyncio.Queue[rpc_pb2.Message]":
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
        packet: rpc_pb2.RPC = rpc_pb2.RPC()
        packet.subscriptions.extend(
            [rpc_pb2.RPC.SubOpts(subscribe=True, topicid=topic_id)]
        )

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
        packet: rpc_pb2.RPC = rpc_pb2.RPC()
        packet.subscriptions.extend(
            [rpc_pb2.RPC.SubOpts(subscribe=False, topicid=topic_id)]
        )

        # Send out unsubscribe message to all peers
        await self.message_all_peers(packet.SerializeToString())

        # Tell router we are leaving this topic
        await self.router.leave(topic_id)

    async def message_all_peers(self, raw_msg: bytes) -> None:
        """
        Broadcast a message to peers
        :param raw_msg: raw contents of the message to broadcast
        """

        # Broadcast message
        for stream in self.peers.values():
            # Write message to stream
            await stream.write(raw_msg)

    async def publish(self, topic_id: str, data: bytes) -> None:
        """
        Publish data to a topic
        :param topic_id: topic which we are going to publish the data to
        :param data: data which we are publishing
        """
        msg = rpc_pb2.Message(
            data=data,
            topicIDs=[topic_id],
            # Origin is ourself.
            from_id=self.host.get_id().to_bytes(),
            seqno=self._next_seqno(),
        )

        # TODO: Sign with our signing key

        await self.push_msg(self.host.get_id(), msg)

    async def validate_msg(self, msg_forwarder: ID, msg: rpc_pb2.Message) -> None:
        """
        Validate the received message
        :param msg_forwarder: the peer who forward us the message.
        :param msg: the message.
        """
        sync_topic_validators = []
        async_topic_validator_futures: List[Awaitable[bool]] = []
        for topic_validator in self.get_msg_validators(msg):
            if topic_validator.is_async:
                async_topic_validator_futures.append(
                    cast(Awaitable[bool], topic_validator.validator(msg_forwarder, msg))
                )
            else:
                sync_topic_validators.append(
                    cast(SyncValidatorFn, topic_validator.validator)
                )

        for validator in sync_topic_validators:
            if not validator(msg_forwarder, msg):
                raise ValidationError(f"Validation failed for msg={msg}")

        # TODO: Implement throttle on async validators

        if len(async_topic_validator_futures) > 0:
            results = await asyncio.gather(*async_topic_validator_futures)
            if not all(results):
                raise ValidationError(f"Validation failed for msg={msg}")

    async def push_msg(self, msg_forwarder: ID, msg: rpc_pb2.Message) -> None:
        """
        Push a pubsub message to others.
        :param msg_forwarder: the peer who forward us the message.
        :param msg: the message we are going to push out.
        """
        # TODO: Check if the `source` is in the blacklist. If yes, reject.

        # TODO: Check if the `from` is in the blacklist. If yes, reject.

        # TODO: Check if signing is required and if so signature should be attached.

        # If the message is processed before, return(i.e., don't further process the message).
        if self._is_msg_seen(msg):
            return

        # TODO: - Validate the message. If failed, reject it.
        # Validate the signature of the message
        # FIXME: `signature_validator` is currently a stub.
        if not signature_validator(msg.key, msg.SerializeToString()):
            log.debug(f"Signature validation failed for msg={msg}")
            return
        # Validate the message with registered topic validators.
        # If the validation failed, return(i.e., don't further process the message).
        try:
            await self.validate_msg(msg_forwarder, msg)
        except ValidationError:
            log.debug(f"Topic validation failed for msg={msg}")
            return

        self._mark_msg_seen(msg)
        await self.handle_talk(msg)
        await self.router.publish(msg_forwarder, msg)

    def _next_seqno(self) -> bytes:
        """
        Make the next message sequence id.
        """
        self.counter += 1
        return self.counter.to_bytes(8, "big")

    def _is_msg_seen(self, msg: rpc_pb2.Message) -> bool:
        msg_id = get_msg_id(msg)
        return msg_id in self.seen_messages

    def _mark_msg_seen(self, msg: rpc_pb2.Message) -> None:
        msg_id = get_msg_id(msg)
        # FIXME: Mapping `msg_id` to `1` is quite awkward. Should investigate if there is a
        #   more appropriate way.
        self.seen_messages[msg_id] = 1

    def _is_subscribed_to_msg(self, msg: rpc_pb2.Message) -> bool:
        if not self.my_topics:
            return False
        return any(topic in self.my_topics for topic in msg.topicIDs)
