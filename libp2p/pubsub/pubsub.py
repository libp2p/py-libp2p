from __future__ import (
    annotations,
)

import base64
from collections.abc import (
    Callable,
    KeysView,
)
import functools
import hashlib
import logging
import time
from typing import (
    NamedTuple,
    cast,
)

import base58
import trio

from libp2p.abc import (
    IHost,
    INetStream,
    IPubsub,
    IPubsubRouter,
    ISubscriptionAPI,
)
from libp2p.crypto.keys import (
    PrivateKey,
)
from libp2p.custom_types import (
    AsyncValidatorFn,
    SyncValidatorFn,
    TProtocol,
    ValidatorFn,
)
from libp2p.exceptions import (
    ParseError,
    ValidationError,
)
from libp2p.io.exceptions import (
    IncompleteReadError,
)
from libp2p.network.exceptions import (
    SwarmException,
)
from libp2p.network.stream.exceptions import (
    StreamClosed,
    StreamEOF,
    StreamReset,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerdata import (
    PeerDataError,
)
from libp2p.tools.async_service import (
    Service,
)
from libp2p.tools.timed_cache.last_seen_cache import (
    LastSeenCache,
)
from libp2p.utils import (
    encode_varint_prefixed,
    read_varint_prefixed_bytes,
)
from libp2p.utils.varint import encode_uvarint

from .pb import (
    rpc_pb2,
)
from .pubsub_notifee import (
    PubsubNotifee,
)
from .subscription import (
    TrioSubscriptionAPI,
)
from .validators import (
    PUBSUB_SIGNING_PREFIX,
    signature_validator,
)

# Ref: https://github.com/libp2p/go-libp2p-pubsub/blob/40e1c94708658b155f30cf99e4574f384756d83c/topic.go#L97  # noqa: E501
SUBSCRIPTION_CHANNEL_SIZE = 32

logger = logging.getLogger("libp2p.pubsub")


def get_peer_and_seqno_msg_id(msg: rpc_pb2.Message) -> bytes:
    # NOTE: `string(from, seqno)` in Go
    return msg.seqno + msg.from_id


def get_content_addressed_msg_id(msg: rpc_pb2.Message) -> bytes:
    return base64.b64encode(hashlib.sha256(msg.data).digest())


class TopicValidator(NamedTuple):
    validator: ValidatorFn
    is_async: bool


class Pubsub(Service, IPubsub):
    host: IHost

    router: IPubsubRouter

    peer_receive_channel: trio.MemoryReceiveChannel[ID]
    dead_peer_receive_channel: trio.MemoryReceiveChannel[ID]

    seen_messages: LastSeenCache

    subscribed_topics_send: dict[str, trio.MemorySendChannel[rpc_pb2.Message]]
    subscribed_topics_receive: dict[str, TrioSubscriptionAPI]

    peer_topics: dict[str, set[ID]]
    peers: dict[ID, INetStream]

    topic_validators: dict[str, TopicValidator]

    counter: int  # uint64

    # Indicate if we should enforce signature verification
    strict_signing: bool
    sign_key: PrivateKey | None

    # Set of blacklisted peer IDs
    blacklisted_peers: set[ID]

    event_handle_peer_queue_started: trio.Event
    event_handle_dead_peer_queue_started: trio.Event

    def __init__(
        self,
        host: IHost,
        router: IPubsubRouter,
        cache_size: int | None = None,
        seen_ttl: int = 120,
        sweep_interval: int = 60,
        strict_signing: bool = True,
        msg_id_constructor: Callable[
            [rpc_pb2.Message], bytes
        ] = get_peer_and_seqno_msg_id,
    ) -> None:
        """
        Construct a new Pubsub object, which is responsible for handling all
        Pubsub-related messages and relaying messages as appropriate to the
        Pubsub router (which is responsible for choosing who to send messages
        to).

        Since the logic for choosing peers to send pubsub messages to is
        in the router, the same Pubsub impl can back floodsub,
        gossipsub, etc.
        """
        self.host = host
        self.router = router

        self._msg_id_constructor = msg_id_constructor

        # Attach this new Pubsub object to the router
        self.router.attach(self)

        peer_send, peer_receive = trio.open_memory_channel[ID](0)
        dead_peer_send, dead_peer_receive = trio.open_memory_channel[ID](0)
        # Only keep the receive channels in `Pubsub`.
        # Therefore, we can only close from the receive side.
        self.peer_receive_channel = peer_receive
        self.dead_peer_receive_channel = dead_peer_receive
        # Register a notifee
        self.host.get_network().register_notifee(
            PubsubNotifee(peer_send, dead_peer_send)
        )

        # Register stream handlers for each pubsub router protocol to handle
        # the pubsub streams opened on those protocols
        for protocol in router.get_protocols():
            self.host.set_stream_handler(protocol, self.stream_handler)

        # keeps track of seen messages as LRU cache
        if cache_size is None:
            self.cache_size = 128
        else:
            self.cache_size = cache_size

        self.strict_signing = strict_signing
        if strict_signing:
            self.sign_key = self.host.get_private_key()
        else:
            self.sign_key = None

        self.seen_messages = LastSeenCache(seen_ttl, sweep_interval)

        # Map of topics we are subscribed to blocking queues
        # for when the given topic receives a message
        self.subscribed_topics_send = {}
        self.subscribed_topics_receive = {}

        # Map of topic to peers to keep track of what peers are subscribed to
        self.peer_topics = {}

        # Create peers map, which maps peer_id (as string) to stream (to a given peer)
        self.peers = {}

        # Map of topic to topic validator
        self.topic_validators = {}

        self.counter = int(time.time())

        # Set of blacklisted peer IDs
        self.blacklisted_peers = set()

        self.event_handle_peer_queue_started = trio.Event()
        self.event_handle_dead_peer_queue_started = trio.Event()

    async def run(self) -> None:
        self.manager.run_daemon_task(self.handle_peer_queue)
        self.manager.run_daemon_task(self.handle_dead_peer_queue)
        await self.manager.wait_finished()

    @property
    def my_id(self) -> ID:
        return self.host.get_id()

    @property
    def protocols(self) -> tuple[TProtocol, ...]:
        return tuple(self.router.get_protocols())

    @property
    def topic_ids(self) -> KeysView[str]:
        return self.subscribed_topics_receive.keys()

    def get_hello_packet(self) -> rpc_pb2.RPC:
        """
        Generate subscription message with all topics we are subscribed to
        only send hello packet if we have subscribed topics.
        """
        packet = rpc_pb2.RPC()
        for topic_id in self.topic_ids:
            packet.subscriptions.extend(
                [rpc_pb2.RPC.SubOpts(subscribe=True, topicid=topic_id)]
            )
        return packet

    async def continuously_read_stream(self, stream: INetStream) -> None:
        """
        Read from input stream in an infinite loop. Process messages from other
        nodes.

        :param stream: stream to continously read from
        """
        peer_id = stream.muxed_conn.peer_id

        try:
            while self.manager.is_running:
                incoming: bytes = await read_varint_prefixed_bytes(stream)
                rpc_incoming: rpc_pb2.RPC = rpc_pb2.RPC()
                rpc_incoming.ParseFromString(incoming)
                if rpc_incoming.publish:
                    # deal with RPC.publish
                    for msg in rpc_incoming.publish:
                        if not self._is_subscribed_to_msg(msg):
                            continue
                        logger.debug(
                            "received `publish` message %s from peer %s", msg, peer_id
                        )
                        self.manager.run_task(self.push_msg, peer_id, msg)

                if rpc_incoming.subscriptions:
                    # deal with RPC.subscriptions
                    # We don't need to relay the subscription to our
                    # peers because a given node only needs its peers
                    # to know that it is subscribed to the topic (doesn't
                    # need everyone to know)
                    for message in rpc_incoming.subscriptions:
                        logger.debug(
                            "received `subscriptions` message %s from peer %s",
                            message,
                            peer_id,
                        )
                        self.handle_subscription(peer_id, message)

                # NOTE: Check if `rpc_incoming.control` is set through `HasField`.
                #   This is necessary because `control` is an optional field in pb2.
                #   Ref: https://developers.google.com/protocol-buffers/docs/reference/python-generated#singular-fields-proto2  # noqa: E501
                if rpc_incoming.HasField("control"):
                    # Pass rpc to router so router could perform custom logic
                    logger.debug(
                        "received `control` message %s from peer %s",
                        rpc_incoming.control,
                        peer_id,
                    )
                    await self.router.handle_rpc(rpc_incoming, peer_id)
        except StreamEOF:
            logger.debug(
                f"Stream closed for peer {peer_id}, exiting read loop cleanly."
            )

    def set_topic_validator(
        self, topic: str, validator: ValidatorFn, is_async_validator: bool
    ) -> None:
        """
        Register a validator under the given topic. One topic can only have one
        validtor.

        :param topic: the topic to register validator under
        :param validator: the validator used to validate messages published to the topic
        :param is_async_validator: indicate if the validator is an asynchronous validator
        """  # noqa: E501
        self.topic_validators[topic] = TopicValidator(validator, is_async_validator)

    def remove_topic_validator(self, topic: str) -> None:
        """
        Remove the validator from the given topic.

        :param topic: the topic to remove validator from
        """
        self.topic_validators.pop(topic, None)

    def get_msg_validators(self, msg: rpc_pb2.Message) -> tuple[TopicValidator, ...]:
        """
        Get all validators corresponding to the topics in the message.

        :param msg: the message published to the topic
        """
        return tuple(
            self.topic_validators[topic]
            for topic in msg.topicIDs
            if topic in self.topic_validators
        )

    def add_to_blacklist(self, peer_id: ID) -> None:
        """
        Add a peer to the blacklist.
        When a peer is blacklisted:
        - Any existing connection to that peer is immediately closed and removed
        - The peer is removed from all topic subscription mappings
        - Future connection attempts from this peer will be rejected
        - Messages forwarded by or originating from this peer will be dropped
        - The peer will not be able to participate in pubsub communication

        :param peer_id: the peer ID to blacklist
        """
        self.blacklisted_peers.add(peer_id)
        logger.debug("Added peer %s to blacklist", peer_id)
        self.manager.run_task(self._teardown_if_connected, peer_id)

    async def _teardown_if_connected(self, peer_id: ID) -> None:
        """Close their stream and remove them if connected"""
        stream = self.peers.get(peer_id)
        if stream is not None:
            try:
                await stream.reset()
            except Exception:
                pass
            del self.peers[peer_id]
        # Also remove from any subscription maps:
        for _topic, peerset in self.peer_topics.items():
            if peer_id in peerset:
                peerset.discard(peer_id)

    def remove_from_blacklist(self, peer_id: ID) -> None:
        """
        Remove a peer from the blacklist.
        Once removed from the blacklist:
        - The peer can establish new connections to this node
        - Messages from this peer will be processed normally
        - The peer can participate in topic subscriptions and message forwarding

        :param peer_id: the peer ID to remove from blacklist
        """
        self.blacklisted_peers.discard(peer_id)
        logger.debug("Removed peer %s from blacklist", peer_id)

    def is_peer_blacklisted(self, peer_id: ID) -> bool:
        """
        Check if a peer is blacklisted.

        :param peer_id: the peer ID to check
        :return: True if peer is blacklisted, False otherwise
        """
        return peer_id in self.blacklisted_peers

    def clear_blacklist(self) -> None:
        """
        Clear all peers from the blacklist.
        This removes all blacklist restrictions, allowing previously blacklisted
        peers to:
        - Establish new connections
        - Send and forward messages
        - Participate in topic subscriptions

        """
        self.blacklisted_peers.clear()
        logger.debug("Cleared all peers from blacklist")

    def get_blacklisted_peers(self) -> set[ID]:
        """
        Get a copy of the current blacklisted peers.
        Returns a snapshot of all currently blacklisted peer IDs. These peers
        are completely isolated from pubsub communication - their connections
        are rejected and their messages are dropped.

        :return: a set containing all blacklisted peer IDs
        """
        return self.blacklisted_peers.copy()

    async def stream_handler(self, stream: INetStream) -> None:
        """
        Stream handler for pubsub. Gets invoked whenever a new stream is
        created on one of the supported pubsub protocols.

        :param stream: newly created stream
        """
        peer_id = stream.muxed_conn.peer_id

        try:
            await self.continuously_read_stream(stream)
        except (StreamEOF, StreamReset, ParseError, IncompleteReadError) as error:
            logger.debug(
                "fail to read from peer %s, error=%s,"
                "closing the stream and remove the peer from record",
                peer_id,
                error,
            )
            await stream.reset()
            self._handle_dead_peer(peer_id)

    async def wait_until_ready(self) -> None:
        await self.event_handle_peer_queue_started.wait()
        await self.event_handle_dead_peer_queue_started.wait()

    async def _handle_new_peer(self, peer_id: ID) -> None:
        if self.is_peer_blacklisted(peer_id):
            logger.debug("Rejecting blacklisted peer %s", peer_id)
            return

        try:
            stream: INetStream = await self.host.new_stream(peer_id, self.protocols)
        except SwarmException as error:
            logger.debug("fail to add new peer %s, error %s", peer_id, error)
            return

        # Send hello packet
        hello = self.get_hello_packet()
        try:
            await stream.write(encode_varint_prefixed(hello.SerializeToString()))
        except StreamClosed:
            logger.debug("Fail to add new peer %s: stream closed", peer_id)
            return
        try:
            self.router.add_peer(peer_id, stream.get_protocol())
        except Exception as error:
            logger.debug("fail to add new peer %s, error %s", peer_id, error)
            return

        self.peers[peer_id] = stream

        logger.debug("added new peer %s", peer_id)

    def _handle_dead_peer(self, peer_id: ID) -> None:
        if peer_id not in self.peers:
            return
        del self.peers[peer_id]

        for topic in self.peer_topics:
            if peer_id in self.peer_topics[topic]:
                self.peer_topics[topic].discard(peer_id)

        self.router.remove_peer(peer_id)

        logger.debug("removed dead peer %s", peer_id)

    async def handle_peer_queue(self) -> None:
        """
        Continuously read from peer queue and each time a new peer is found,
        open a stream to the peer using a supported pubsub protocol pubsub
        protocols we support.
        """
        async with self.peer_receive_channel:
            self.event_handle_peer_queue_started.set()
            async for peer_id in self.peer_receive_channel:
                # Add Peer
                self.manager.run_task(self._handle_new_peer, peer_id)

    async def handle_dead_peer_queue(self) -> None:
        """
        Continuously read from dead peer channel and close the stream
        between that peer and remove peer info from pubsub and pubsub router.
        """
        async with self.dead_peer_receive_channel:
            self.event_handle_dead_peer_queue_started.set()
            async for peer_id in self.dead_peer_receive_channel:
                # Remove Peer
                self._handle_dead_peer(peer_id)

    def handle_subscription(
        self, origin_id: ID, sub_message: rpc_pb2.RPC.SubOpts
    ) -> None:
        """
        Handle an incoming subscription message from a peer. Update internal
        mapping to mark the peer as subscribed or unsubscribed to topics as
        defined in the subscription message.

        :param origin_id: id of the peer who subscribe to the message
        :param sub_message: RPC.SubOpts
        """
        if sub_message.subscribe:
            if sub_message.topicid not in self.peer_topics:
                self.peer_topics[sub_message.topicid] = {origin_id}
            elif origin_id not in self.peer_topics[sub_message.topicid]:
                # Add peer to topic
                self.peer_topics[sub_message.topicid].add(origin_id)
        else:
            if sub_message.topicid in self.peer_topics:
                if origin_id in self.peer_topics[sub_message.topicid]:
                    self.peer_topics[sub_message.topicid].discard(origin_id)

    def notify_subscriptions(self, publish_message: rpc_pb2.Message) -> None:
        """
        Put incoming message from a peer onto my blocking queue.

        :param publish_message: RPC.Message format
        """
        # Check if this message has any topics that we are subscribed to
        for topic in publish_message.topicIDs:
            if topic in self.topic_ids:
                # we are subscribed to a topic this message was sent for,
                # so add message to the subscription output queue
                # for each topic
                try:
                    self.subscribed_topics_send[topic].send_nowait(publish_message)
                except trio.WouldBlock:
                    # Channel is full, ignore this message.
                    logger.warning(
                        "fail to deliver message to subscription for topic %s", topic
                    )

    async def subscribe(self, topic_id: str) -> ISubscriptionAPI:
        """
        Subscribe ourself to a topic.

        :param topic_id: topic_id to subscribe to
        """
        logger.debug("subscribing to topic %s", topic_id)

        # Already subscribed
        if topic_id in self.topic_ids:
            return self.subscribed_topics_receive[topic_id]

        send_channel, receive_channel = trio.open_memory_channel[rpc_pb2.Message](
            SUBSCRIPTION_CHANNEL_SIZE
        )

        subscription = TrioSubscriptionAPI(
            receive_channel,
            unsubscribe_fn=functools.partial(self.unsubscribe, topic_id),
        )
        self.subscribed_topics_send[topic_id] = send_channel
        self.subscribed_topics_receive[topic_id] = subscription

        # Create subscribe message
        packet: rpc_pb2.RPC = rpc_pb2.RPC()
        packet.subscriptions.extend(
            [rpc_pb2.RPC.SubOpts(subscribe=True, topicid=topic_id)]
        )

        # Send out subscribe message to all peers
        await self.message_all_peers(packet.SerializeToString())

        # Tell router we are joining this topic
        await self.router.join(topic_id)

        # Return the subscription for messages on this topic
        return subscription

    async def unsubscribe(self, topic_id: str) -> None:
        """
        Unsubscribe ourself from a topic.

        :param topic_id: topic_id to unsubscribe from
        """
        logger.debug("unsubscribing from topic %s", topic_id)

        # Return if we already unsubscribed from the topic
        if topic_id not in self.topic_ids:
            return
        # Remove topic_id from the maps before yielding
        send_channel = self.subscribed_topics_send[topic_id]
        del self.subscribed_topics_send[topic_id]
        del self.subscribed_topics_receive[topic_id]
        # Only close the send side
        await send_channel.aclose()

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
        Broadcast a message to peers.

        :param raw_msg: raw contents of the message to broadcast
        """
        # Broadcast message
        for stream in self.peers.values():
            # Write message to stream
            try:
                await stream.write(encode_varint_prefixed(raw_msg))
            except StreamClosed:
                peer_id = stream.muxed_conn.peer_id
                logger.debug("Fail to message peer %s: stream closed", peer_id)
                self._handle_dead_peer(peer_id)

    async def publish(self, topic_id: str | list[str], data: bytes) -> None:
        """
        Publish data to a topic or multiple topics.

        :param topic_id: topic (str) or topics (list[str]) to publish the data to
        :param data: data which we are publishing
        """
        # Handle both single topic (str) and multiple topics (list[str])
        if isinstance(topic_id, str):
            topic_ids = [topic_id]
        else:
            topic_ids = topic_id

        msg = rpc_pb2.Message(
            data=data,
            topicIDs=topic_ids,
            # Origin is ourself.
            from_id=self.my_id.to_bytes(),
            seqno=self._next_seqno(),
        )

        if self.strict_signing:
            priv_key = self.sign_key
            if priv_key is None:
                raise PeerDataError("private key not found")

            signature = priv_key.sign(
                PUBSUB_SIGNING_PREFIX.encode() + msg.SerializeToString()
            )
            msg.key = self.host.get_public_key().serialize()
            msg.signature = signature

        await self.push_msg(self.my_id, msg)

        logger.debug("successfully published message %s", msg)

    async def validate_msg(self, msg_forwarder: ID, msg: rpc_pb2.Message) -> None:
        """
        Validate the received message.

        :param msg_forwarder: the peer who forward us the message.
        :param msg: the message.
        """
        sync_topic_validators: list[SyncValidatorFn] = []
        async_topic_validators: list[AsyncValidatorFn] = []
        for topic_validator in self.get_msg_validators(msg):
            if topic_validator.is_async:
                async_topic_validators.append(
                    cast(AsyncValidatorFn, topic_validator.validator)
                )
            else:
                sync_topic_validators.append(
                    cast(SyncValidatorFn, topic_validator.validator)
                )

        for validator in sync_topic_validators:
            if not validator(msg_forwarder, msg):
                raise ValidationError(f"Validation failed for msg={msg}")

        # TODO: Implement throttle on async validators

        if len(async_topic_validators) > 0:
            # Appends to lists are thread safe in CPython
            results = []

            async def run_async_validator(func: AsyncValidatorFn) -> None:
                result = await func(msg_forwarder, msg)
                results.append(result)

            async with trio.open_nursery() as nursery:
                for async_validator in async_topic_validators:
                    nursery.start_soon(run_async_validator, async_validator)

            if not all(results):
                raise ValidationError(f"Validation failed for msg={msg}")

    async def push_msg(self, msg_forwarder: ID, msg: rpc_pb2.Message) -> None:
        """
        Push a pubsub message to others.

        :param msg_forwarder: the peer who forward us the message.
        :param msg: the message we are going to push out.
        """
        logger.debug("attempting to publish message %s", msg)

        # Check if the message forwarder (source) is in the blacklist. If yes, reject.
        if self.is_peer_blacklisted(msg_forwarder):
            logger.debug(
                "Rejecting message from blacklisted source peer %s", msg_forwarder
            )
            return

        # Check if the message originator (from) is in the blacklist. If yes, reject.
        msg_from_peer = ID(msg.from_id)
        if self.is_peer_blacklisted(msg_from_peer):
            logger.debug(
                "Rejecting message from blacklisted originator peer %s", msg_from_peer
            )
            return

        # If the message is processed before, return(i.e., don't further process the message)  # noqa: E501
        if self._is_msg_seen(msg):
            return

        # Check if signing is required and if so validate the signature
        if self.strict_signing:
            # Validate the signature of the message
            if not signature_validator(msg):
                logger.debug("Signature validation failed for msg: %s", msg)
                return

        # Validate the message with registered topic validators.
        # If the validation failed, return(i.e., don't further process the message).
        try:
            await self.validate_msg(msg_forwarder, msg)
        except ValidationError:
            logger.debug(
                "Topic validation failed: sender %s sent data %s under topic IDs: %s %s:%s",  # noqa: E501
                msg_forwarder,
                msg.data.hex(),
                msg.topicIDs,
                base58.b58encode(msg.from_id).decode(),
                msg.seqno.hex(),
            )
            return

        self._mark_msg_seen(msg)

        # reject messages claiming to be from ourselves but not locally published
        self_id = self.host.get_id()
        if (
            base58.b58encode(msg.from_id).decode() == self_id
            and msg_forwarder != self_id
        ):
            logger.debug(
                "dropping message claiming to be from self but forwarded from %s",
                msg_forwarder,
            )
            return

        self.notify_subscriptions(msg)
        await self.router.publish(msg_forwarder, msg)

    def _next_seqno(self) -> bytes:
        """Make the next message sequence id."""
        self.counter += 1
        return self.counter.to_bytes(8, "big")

    def _is_msg_seen(self, msg: rpc_pb2.Message) -> bool:
        msg_id = self._msg_id_constructor(msg)
        return self.seen_messages.has(msg_id)

    def _mark_msg_seen(self, msg: rpc_pb2.Message) -> None:
        msg_id = self._msg_id_constructor(msg)
        self.seen_messages.add(msg_id)

    def _is_subscribed_to_msg(self, msg: rpc_pb2.Message) -> bool:
        return any(topic in self.topic_ids for topic in msg.topicIDs)

    async def write_msg(self, stream: INetStream, rpc_msg: rpc_pb2.RPC) -> bool:
        """
        Write an RPC message to a stream with proper error handling.

        Implements WriteMsg similar to go-msgio which is used in go-libp2p
        Ref: https://github.com/libp2p/go-msgio/blob/master/protoio/uvarint_writer.go#L56


        :param stream: stream to write the message to
        :param rpc_msg: RPC message to write
        :return: True if successful, False if stream was closed
        """
        try:
            # Calculate message size first
            msg_bytes = rpc_msg.SerializeToString()
            msg_size = len(msg_bytes)

            # Calculate varint size and allocate exact buffer size needed

            varint_bytes = encode_uvarint(msg_size)
            varint_size = len(varint_bytes)

            # Allocate buffer with exact size (like Go's pool.Get())
            buf = bytearray(varint_size + msg_size)

            # Write varint length prefix to buffer (like Go's binary.PutUvarint())
            buf[:varint_size] = varint_bytes

            # Write serialized message after varint (like Go's rpc.MarshalTo())
            buf[varint_size:] = msg_bytes

            # Single write operation (like Go's s.Write(buf))
            await stream.write(bytes(buf))
            return True
        except StreamClosed:
            peer_id = stream.muxed_conn.peer_id
            logger.debug("Fail to write message to %s: stream closed", peer_id)
            self._handle_dead_peer(peer_id)
            return False
