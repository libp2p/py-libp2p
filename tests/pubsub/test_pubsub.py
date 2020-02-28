from contextlib import contextmanager
from typing import NamedTuple

import pytest
import trio

from libp2p.exceptions import ValidationError
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.pubsub import PUBSUB_SIGNING_PREFIX, SUBSCRIPTION_CHANNEL_SIZE
from libp2p.tools.constants import MAX_READ_LEN
from libp2p.tools.factories import IDFactory, PubsubFactory, net_stream_pair_factory
from libp2p.tools.pubsub.utils import make_pubsub_msg
from libp2p.tools.utils import connect
from libp2p.utils import encode_varint_prefixed

TESTING_TOPIC = "TEST_SUBSCRIBE"
TESTING_DATA = b"data"


@pytest.mark.trio
async def test_subscribe_and_unsubscribe():
    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:
        await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
        assert TESTING_TOPIC in pubsubs_fsub[0].topic_ids

        await pubsubs_fsub[0].unsubscribe(TESTING_TOPIC)
        assert TESTING_TOPIC not in pubsubs_fsub[0].topic_ids


@pytest.mark.trio
async def test_re_subscribe():
    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:
        await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
        assert TESTING_TOPIC in pubsubs_fsub[0].topic_ids

        await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
        assert TESTING_TOPIC in pubsubs_fsub[0].topic_ids


@pytest.mark.trio
async def test_re_unsubscribe():
    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:
        # Unsubscribe from topic we didn't even subscribe to
        assert "NOT_MY_TOPIC" not in pubsubs_fsub[0].topic_ids
        await pubsubs_fsub[0].unsubscribe("NOT_MY_TOPIC")
        assert "NOT_MY_TOPIC" not in pubsubs_fsub[0].topic_ids

        await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
        assert TESTING_TOPIC in pubsubs_fsub[0].topic_ids

        await pubsubs_fsub[0].unsubscribe(TESTING_TOPIC)
        assert TESTING_TOPIC not in pubsubs_fsub[0].topic_ids

        await pubsubs_fsub[0].unsubscribe(TESTING_TOPIC)
        assert TESTING_TOPIC not in pubsubs_fsub[0].topic_ids


@pytest.mark.trio
async def test_peers_subscribe():
    async with PubsubFactory.create_batch_with_floodsub(2) as pubsubs_fsub:
        await connect(pubsubs_fsub[0].host, pubsubs_fsub[1].host)
        await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
        # Yield to let 0 notify 1
        await trio.sleep(1)
        assert pubsubs_fsub[0].my_id in pubsubs_fsub[1].peer_topics[TESTING_TOPIC]
        await pubsubs_fsub[0].unsubscribe(TESTING_TOPIC)
        # Yield to let 0 notify 1
        await trio.sleep(1)
        assert pubsubs_fsub[0].my_id not in pubsubs_fsub[1].peer_topics[TESTING_TOPIC]


@pytest.mark.trio
async def test_get_hello_packet():
    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:

        def _get_hello_packet_topic_ids():
            packet = pubsubs_fsub[0].get_hello_packet()
            return tuple(sub.topicid for sub in packet.subscriptions)

        # Test: No subscription, so there should not be any topic ids in the hello packet.
        assert len(_get_hello_packet_topic_ids()) == 0

        # Test: After subscriptions, topic ids should be in the hello packet.
        topic_ids = ["t", "o", "p", "i", "c"]
        for topic in topic_ids:
            await pubsubs_fsub[0].subscribe(topic)
        topic_ids_in_hello = _get_hello_packet_topic_ids()
        for topic in topic_ids:
            assert topic in topic_ids_in_hello


@pytest.mark.trio
async def test_set_and_remove_topic_validator():
    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:
        is_sync_validator_called = False

        def sync_validator(peer_id, msg):
            nonlocal is_sync_validator_called
            is_sync_validator_called = True

        is_async_validator_called = False

        async def async_validator(peer_id, msg):
            nonlocal is_async_validator_called
            is_async_validator_called = True
            await trio.hazmat.checkpoint()

        topic = "TEST_VALIDATOR"

        assert topic not in pubsubs_fsub[0].topic_validators

        # Register sync validator
        pubsubs_fsub[0].set_topic_validator(topic, sync_validator, False)

        assert topic in pubsubs_fsub[0].topic_validators
        topic_validator = pubsubs_fsub[0].topic_validators[topic]
        assert not topic_validator.is_async

        # Validate with sync validator
        topic_validator.validator(peer_id=IDFactory(), msg="msg")

        assert is_sync_validator_called
        assert not is_async_validator_called

        # Register with async validator
        pubsubs_fsub[0].set_topic_validator(topic, async_validator, True)

        is_sync_validator_called = False
        assert topic in pubsubs_fsub[0].topic_validators
        topic_validator = pubsubs_fsub[0].topic_validators[topic]
        assert topic_validator.is_async

        # Validate with async validator
        await topic_validator.validator(peer_id=IDFactory(), msg="msg")

        assert is_async_validator_called
        assert not is_sync_validator_called

        # Remove validator
        pubsubs_fsub[0].remove_topic_validator(topic)
        assert topic not in pubsubs_fsub[0].topic_validators


@pytest.mark.trio
async def test_get_msg_validators():
    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:
        times_sync_validator_called = 0

        def sync_validator(peer_id, msg):
            nonlocal times_sync_validator_called
            times_sync_validator_called += 1

        times_async_validator_called = 0

        async def async_validator(peer_id, msg):
            nonlocal times_async_validator_called
            times_async_validator_called += 1
            await trio.hazmat.checkpoint()

        topic_1 = "TEST_VALIDATOR_1"
        topic_2 = "TEST_VALIDATOR_2"
        topic_3 = "TEST_VALIDATOR_3"

        # Register sync validator for topic 1 and 2
        pubsubs_fsub[0].set_topic_validator(topic_1, sync_validator, False)
        pubsubs_fsub[0].set_topic_validator(topic_2, sync_validator, False)

        # Register async validator for topic 3
        pubsubs_fsub[0].set_topic_validator(topic_3, async_validator, True)

        msg = make_pubsub_msg(
            origin_id=pubsubs_fsub[0].my_id,
            topic_ids=[topic_1, topic_2, topic_3],
            data=b"1234",
            seqno=b"\x00" * 8,
        )

        topic_validators = pubsubs_fsub[0].get_msg_validators(msg)
        for topic_validator in topic_validators:
            if topic_validator.is_async:
                await topic_validator.validator(peer_id=IDFactory(), msg="msg")
            else:
                topic_validator.validator(peer_id=IDFactory(), msg="msg")

        assert times_sync_validator_called == 2
        assert times_async_validator_called == 1


@pytest.mark.parametrize(
    "is_topic_1_val_passed, is_topic_2_val_passed",
    ((False, True), (True, False), (True, True)),
)
@pytest.mark.trio
async def test_validate_msg(is_topic_1_val_passed, is_topic_2_val_passed):
    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:

        def passed_sync_validator(peer_id, msg):
            return True

        def failed_sync_validator(peer_id, msg):
            return False

        async def passed_async_validator(peer_id, msg):
            await trio.hazmat.checkpoint()
            return True

        async def failed_async_validator(peer_id, msg):
            await trio.hazmat.checkpoint()
            return False

        topic_1 = "TEST_SYNC_VALIDATOR"
        topic_2 = "TEST_ASYNC_VALIDATOR"

        if is_topic_1_val_passed:
            pubsubs_fsub[0].set_topic_validator(topic_1, passed_sync_validator, False)
        else:
            pubsubs_fsub[0].set_topic_validator(topic_1, failed_sync_validator, False)

        if is_topic_2_val_passed:
            pubsubs_fsub[0].set_topic_validator(topic_2, passed_async_validator, True)
        else:
            pubsubs_fsub[0].set_topic_validator(topic_2, failed_async_validator, True)

        msg = make_pubsub_msg(
            origin_id=pubsubs_fsub[0].my_id,
            topic_ids=[topic_1, topic_2],
            data=b"1234",
            seqno=b"\x00" * 8,
        )

        if is_topic_1_val_passed and is_topic_2_val_passed:
            await pubsubs_fsub[0].validate_msg(pubsubs_fsub[0].my_id, msg)
        else:
            with pytest.raises(ValidationError):
                await pubsubs_fsub[0].validate_msg(pubsubs_fsub[0].my_id, msg)


@pytest.mark.trio
async def test_continuously_read_stream(monkeypatch, nursery, security_protocol):
    async def wait_for_event_occurring(event):
        await trio.hazmat.checkpoint()
        with trio.fail_after(0.1):
            await event.wait()

    class Events(NamedTuple):
        push_msg: trio.Event
        handle_subscription: trio.Event
        handle_rpc: trio.Event

    @contextmanager
    def mock_methods():
        event_push_msg = trio.Event()
        event_handle_subscription = trio.Event()
        event_handle_rpc = trio.Event()

        async def mock_push_msg(msg_forwarder, msg):
            event_push_msg.set()
            await trio.hazmat.checkpoint()

        def mock_handle_subscription(origin_id, sub_message):
            event_handle_subscription.set()

        async def mock_handle_rpc(rpc, sender_peer_id):
            event_handle_rpc.set()
            await trio.hazmat.checkpoint()

        with monkeypatch.context() as m:
            m.setattr(pubsubs_fsub[0], "push_msg", mock_push_msg)
            m.setattr(pubsubs_fsub[0], "handle_subscription", mock_handle_subscription)
            m.setattr(pubsubs_fsub[0].router, "handle_rpc", mock_handle_rpc)
            yield Events(event_push_msg, event_handle_subscription, event_handle_rpc)

    async with PubsubFactory.create_batch_with_floodsub(
        1, security_protocol=security_protocol
    ) as pubsubs_fsub, net_stream_pair_factory(
        security_protocol=security_protocol
    ) as stream_pair:
        await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
        # Kick off the task `continuously_read_stream`
        nursery.start_soon(pubsubs_fsub[0].continuously_read_stream, stream_pair[0])

        # Test: `push_msg` is called when publishing to a subscribed topic.
        publish_subscribed_topic = rpc_pb2.RPC(
            publish=[rpc_pb2.Message(topicIDs=[TESTING_TOPIC])]
        )
        with mock_methods() as events:
            await stream_pair[1].write(
                encode_varint_prefixed(publish_subscribed_topic.SerializeToString())
            )
            await wait_for_event_occurring(events.push_msg)
            # Make sure the other events are not emitted.
            with pytest.raises(trio.TooSlowError):
                await wait_for_event_occurring(events.handle_subscription)
            with pytest.raises(trio.TooSlowError):
                await wait_for_event_occurring(events.handle_rpc)

        # Test: `push_msg` is not called when publishing to a topic-not-subscribed.
        publish_not_subscribed_topic = rpc_pb2.RPC(
            publish=[rpc_pb2.Message(topicIDs=["NOT_SUBSCRIBED"])]
        )
        with mock_methods() as events:
            await stream_pair[1].write(
                encode_varint_prefixed(publish_not_subscribed_topic.SerializeToString())
            )
            with pytest.raises(trio.TooSlowError):
                await wait_for_event_occurring(events.push_msg)

        # Test: `handle_subscription` is called when a subscription message is received.
        subscription_msg = rpc_pb2.RPC(subscriptions=[rpc_pb2.RPC.SubOpts()])
        with mock_methods() as events:
            await stream_pair[1].write(
                encode_varint_prefixed(subscription_msg.SerializeToString())
            )
            await wait_for_event_occurring(events.handle_subscription)
            # Make sure the other events are not emitted.
            with pytest.raises(trio.TooSlowError):
                await wait_for_event_occurring(events.push_msg)
            with pytest.raises(trio.TooSlowError):
                await wait_for_event_occurring(events.handle_rpc)

        # Test: `handle_rpc` is called when a control message is received.
        control_msg = rpc_pb2.RPC(control=rpc_pb2.ControlMessage())
        with mock_methods() as events:
            await stream_pair[1].write(
                encode_varint_prefixed(control_msg.SerializeToString())
            )
            await wait_for_event_occurring(events.handle_rpc)
            # Make sure the other events are not emitted.
            with pytest.raises(trio.TooSlowError):
                await wait_for_event_occurring(events.push_msg)
            with pytest.raises(trio.TooSlowError):
                await wait_for_event_occurring(events.handle_subscription)


# TODO: Add the following tests after they are aligned with Go.
#   (Issue #191: https://github.com/libp2p/py-libp2p/issues/191)
#         - `test_stream_handler`
#         - `test_handle_peer_queue`


@pytest.mark.trio
async def test_handle_subscription():
    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:
        assert len(pubsubs_fsub[0].peer_topics) == 0
        sub_msg_0 = rpc_pb2.RPC.SubOpts(subscribe=True, topicid=TESTING_TOPIC)
        peer_ids = [IDFactory() for _ in range(2)]
        # Test: One peer is subscribed
        pubsubs_fsub[0].handle_subscription(peer_ids[0], sub_msg_0)
        assert (
            len(pubsubs_fsub[0].peer_topics) == 1
            and TESTING_TOPIC in pubsubs_fsub[0].peer_topics
        )
        assert len(pubsubs_fsub[0].peer_topics[TESTING_TOPIC]) == 1
        assert peer_ids[0] in pubsubs_fsub[0].peer_topics[TESTING_TOPIC]
        # Test: Another peer is subscribed
        pubsubs_fsub[0].handle_subscription(peer_ids[1], sub_msg_0)
        assert len(pubsubs_fsub[0].peer_topics) == 1
        assert len(pubsubs_fsub[0].peer_topics[TESTING_TOPIC]) == 2
        assert peer_ids[1] in pubsubs_fsub[0].peer_topics[TESTING_TOPIC]
        # Test: Subscribe to another topic
        another_topic = "ANOTHER_TOPIC"
        sub_msg_1 = rpc_pb2.RPC.SubOpts(subscribe=True, topicid=another_topic)
        pubsubs_fsub[0].handle_subscription(peer_ids[0], sub_msg_1)
        assert len(pubsubs_fsub[0].peer_topics) == 2
        assert another_topic in pubsubs_fsub[0].peer_topics
        assert peer_ids[0] in pubsubs_fsub[0].peer_topics[another_topic]
        # Test: unsubscribe
        unsub_msg = rpc_pb2.RPC.SubOpts(subscribe=False, topicid=TESTING_TOPIC)
        pubsubs_fsub[0].handle_subscription(peer_ids[0], unsub_msg)
        assert peer_ids[0] not in pubsubs_fsub[0].peer_topics[TESTING_TOPIC]


@pytest.mark.trio
async def test_handle_talk():
    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:
        sub = await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
        msg_0 = make_pubsub_msg(
            origin_id=pubsubs_fsub[0].my_id,
            topic_ids=[TESTING_TOPIC],
            data=b"1234",
            seqno=b"\x00" * 8,
        )
        pubsubs_fsub[0].notify_subscriptions(msg_0)
        msg_1 = make_pubsub_msg(
            origin_id=pubsubs_fsub[0].my_id,
            topic_ids=["NOT_SUBSCRIBED"],
            data=b"1234",
            seqno=b"\x11" * 8,
        )
        pubsubs_fsub[0].notify_subscriptions(msg_1)
        assert (
            len(pubsubs_fsub[0].topic_ids) == 1
            and sub == pubsubs_fsub[0].subscribed_topics_receive[TESTING_TOPIC]
        )
        assert (await sub.get()) == msg_0


@pytest.mark.trio
async def test_message_all_peers(monkeypatch, security_protocol):
    async with PubsubFactory.create_batch_with_floodsub(
        1, security_protocol=security_protocol
    ) as pubsubs_fsub, net_stream_pair_factory(
        security_protocol=security_protocol
    ) as stream_pair:
        peer_id = IDFactory()
        mock_peers = {peer_id: stream_pair[0]}
        with monkeypatch.context() as m:
            m.setattr(pubsubs_fsub[0], "peers", mock_peers)

            empty_rpc = rpc_pb2.RPC()
            empty_rpc_bytes = empty_rpc.SerializeToString()
            empty_rpc_bytes_len_prefixed = encode_varint_prefixed(empty_rpc_bytes)
            await pubsubs_fsub[0].message_all_peers(empty_rpc_bytes)
            assert (
                await stream_pair[1].read(MAX_READ_LEN)
            ) == empty_rpc_bytes_len_prefixed


@pytest.mark.trio
async def test_subscribe_and_publish():
    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:
        pubsub = pubsubs_fsub[0]

        list_data = [b"d0", b"d1"]
        event_receive_data_started = trio.Event()

        async def publish_data(topic):
            await event_receive_data_started.wait()
            for data in list_data:
                await pubsub.publish(topic, data)

        async def receive_data(topic):
            i = 0
            event_receive_data_started.set()
            assert topic not in pubsub.topic_ids
            subscription = await pubsub.subscribe(topic)
            async with subscription:
                assert topic in pubsub.topic_ids
                async for msg in subscription:
                    assert msg.data == list_data[i]
                    i += 1
                    if i == len(list_data):
                        break
            assert topic not in pubsub.topic_ids

        async with trio.open_nursery() as nursery:
            nursery.start_soon(receive_data, TESTING_TOPIC)
            nursery.start_soon(publish_data, TESTING_TOPIC)


@pytest.mark.trio
async def test_subscribe_and_publish_full_channel():
    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:
        pubsub = pubsubs_fsub[0]

        extra_data_0 = b"extra_data_0"
        extra_data_1 = b"extra_data_1"

        # Test: Subscription channel is of size `SUBSCRIPTION_CHANNEL_SIZE`.
        #   When the channel is full, new received messages are dropped.
        #   After the channel has empty slot, the channel can receive new messages.

        # Assume `SUBSCRIPTION_CHANNEL_SIZE` is smaller than `2**(4*8)`.
        list_data = [i.to_bytes(4, "big") for i in range(SUBSCRIPTION_CHANNEL_SIZE)]
        # Expect `extra_data_0` is dropped and `extra_data_1` is appended.
        expected_list_data = list_data + [extra_data_1]

        subscription = await pubsub.subscribe(TESTING_TOPIC)
        for data in list_data:
            await pubsub.publish(TESTING_TOPIC, data)

        # Publish `extra_data_0` which should be dropped since the channel is already full.
        await pubsub.publish(TESTING_TOPIC, extra_data_0)
        # Consume a message and there is an empty slot in the channel.
        assert (await subscription.get()).data == expected_list_data.pop(0)
        # Publish `extra_data_1` which should be appended to the channel.
        await pubsub.publish(TESTING_TOPIC, extra_data_1)

        for expected_data in expected_list_data:
            assert (await subscription.get()).data == expected_data


@pytest.mark.trio
async def test_publish_push_msg_is_called(monkeypatch):
    msg_forwarders = []
    msgs = []

    async def push_msg(msg_forwarder, msg):
        msg_forwarders.append(msg_forwarder)
        msgs.append(msg)
        await trio.hazmat.checkpoint()

    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:
        with monkeypatch.context() as m:
            m.setattr(pubsubs_fsub[0], "push_msg", push_msg)

            await pubsubs_fsub[0].publish(TESTING_TOPIC, TESTING_DATA)
            await pubsubs_fsub[0].publish(TESTING_TOPIC, TESTING_DATA)

            assert (
                len(msgs) == 2
            ), "`push_msg` should be called every time `publish` is called"
            assert (msg_forwarders[0] == msg_forwarders[1]) and (
                msg_forwarders[1] == pubsubs_fsub[0].my_id
            )
            assert (
                msgs[0].seqno != msgs[1].seqno
            ), "`seqno` should be different every time"


@pytest.mark.trio
async def test_push_msg(monkeypatch):
    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:
        msg_0 = make_pubsub_msg(
            origin_id=pubsubs_fsub[0].my_id,
            topic_ids=[TESTING_TOPIC],
            data=TESTING_DATA,
            seqno=b"\x00" * 8,
        )

        @contextmanager
        def mock_router_publish():

            event = trio.Event()

            async def router_publish(*args, **kwargs):
                event.set()
                await trio.hazmat.checkpoint()

            with monkeypatch.context() as m:
                m.setattr(pubsubs_fsub[0].router, "publish", router_publish)
                yield event

        with mock_router_publish() as event:
            # Test: `msg` is not seen before `push_msg`, and is seen after `push_msg`.
            assert not pubsubs_fsub[0]._is_msg_seen(msg_0)
            await pubsubs_fsub[0].push_msg(pubsubs_fsub[0].my_id, msg_0)
            assert pubsubs_fsub[0]._is_msg_seen(msg_0)
            # Test: Ensure `router.publish` is called in `push_msg`
            with trio.fail_after(0.1):
                await event.wait()

        with mock_router_publish() as event:
            # Test: `push_msg` the message again and it will be reject.
            #   `router_publish` is not called then.
            await pubsubs_fsub[0].push_msg(pubsubs_fsub[0].my_id, msg_0)
            await trio.sleep(0.01)
            assert not event.is_set()

            sub = await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
            # Test: `push_msg` succeeds with another unseen msg.
            msg_1 = make_pubsub_msg(
                origin_id=pubsubs_fsub[0].my_id,
                topic_ids=[TESTING_TOPIC],
                data=TESTING_DATA,
                seqno=b"\x11" * 8,
            )
            assert not pubsubs_fsub[0]._is_msg_seen(msg_1)
            await pubsubs_fsub[0].push_msg(pubsubs_fsub[0].my_id, msg_1)
            assert pubsubs_fsub[0]._is_msg_seen(msg_1)
            with trio.fail_after(0.1):
                await event.wait()
            # Test: Subscribers are notified when `push_msg` new messages.
            assert (await sub.get()) == msg_1

        with mock_router_publish() as event:
            # Test: add a topic validator and `push_msg` the message that
            # does not pass the validation.
            # `router_publish` is not called then.
            def failed_sync_validator(peer_id, msg):
                return False

            pubsubs_fsub[0].set_topic_validator(
                TESTING_TOPIC, failed_sync_validator, False
            )

            msg_2 = make_pubsub_msg(
                origin_id=pubsubs_fsub[0].my_id,
                topic_ids=[TESTING_TOPIC],
                data=TESTING_DATA,
                seqno=b"\x22" * 8,
            )

            await pubsubs_fsub[0].push_msg(pubsubs_fsub[0].my_id, msg_2)
            await trio.sleep(0.01)
            assert not event.is_set()


@pytest.mark.trio
async def test_strict_signing():
    async with PubsubFactory.create_batch_with_floodsub(
        2, strict_signing=True
    ) as pubsubs_fsub:
        await connect(pubsubs_fsub[0].host, pubsubs_fsub[1].host)
        await pubsubs_fsub[0].subscribe(TESTING_TOPIC)
        await pubsubs_fsub[1].subscribe(TESTING_TOPIC)
        await trio.sleep(1)

        await pubsubs_fsub[0].publish(TESTING_TOPIC, TESTING_DATA)
        await trio.sleep(1)

        assert len(pubsubs_fsub[0].seen_messages) == 1
        assert len(pubsubs_fsub[1].seen_messages) == 1


@pytest.mark.trio
async def test_strict_signing_failed_validation(monkeypatch):
    async with PubsubFactory.create_batch_with_floodsub(
        2, strict_signing=True
    ) as pubsubs_fsub:
        msg = make_pubsub_msg(
            origin_id=pubsubs_fsub[0].my_id,
            topic_ids=[TESTING_TOPIC],
            data=TESTING_DATA,
            seqno=b"\x00" * 8,
        )
        priv_key = pubsubs_fsub[0].sign_key
        signature = priv_key.sign(
            PUBSUB_SIGNING_PREFIX.encode() + msg.SerializeToString()
        )

        event = trio.Event()

        def _is_msg_seen(msg):
            return False

        # Use router publish to check if `push_msg` succeed.
        async def router_publish(*args, **kwargs):
            await trio.hazmat.checkpoint()
            # The event will only be set if `push_msg` succeed.
            event.set()

        monkeypatch.setattr(pubsubs_fsub[0], "_is_msg_seen", _is_msg_seen)
        monkeypatch.setattr(pubsubs_fsub[0].router, "publish", router_publish)

        # Test: no signature attached in `msg`
        await pubsubs_fsub[0].push_msg(pubsubs_fsub[0].my_id, msg)
        await trio.sleep(0.01)
        assert not event.is_set()

        # Test: `msg.key` does not match `msg.from_id`
        msg.key = pubsubs_fsub[1].host.get_public_key().serialize()
        msg.signature = signature
        await pubsubs_fsub[0].push_msg(pubsubs_fsub[0].my_id, msg)
        await trio.sleep(0.01)
        assert not event.is_set()

        # Test: invalid signature
        msg.key = pubsubs_fsub[0].host.get_public_key().serialize()
        msg.signature = b"\x12" * 100
        await pubsubs_fsub[0].push_msg(pubsubs_fsub[0].my_id, msg)
        await trio.sleep(0.01)
        assert not event.is_set()

        # Finally, assert the signature indeed will pass validation
        msg.key = pubsubs_fsub[0].host.get_public_key().serialize()
        msg.signature = signature
        await pubsubs_fsub[0].push_msg(pubsubs_fsub[0].my_id, msg)
        await trio.sleep(0.01)
        assert event.is_set()
