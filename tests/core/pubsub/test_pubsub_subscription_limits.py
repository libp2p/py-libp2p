"""Tests for pubsub subscription flood protections (GHSA-4f8r-922h-2vgv)."""

from typing import cast

import pytest
import trio

from libp2p.abc import INetStream
from libp2p.pubsub.pb import rpc_pb2
from libp2p.tools.utils import connect
from libp2p.utils import encode_varint_prefixed
from tests.utils.factories import IDFactory, PubsubFactory, net_stream_pair_factory

pytestmark = pytest.mark.trio


@pytest.mark.trio
async def test_unsubscribe_removes_empty_topic_key():
    async with PubsubFactory.create_batch_with_gossipsub(1) as pubsubs:
        peer_id = IDFactory()
        topic = "topic-unsub-cleanup"
        pubsubs[0].handle_subscription(
            peer_id, rpc_pb2.RPC.SubOpts(subscribe=True, topicid=topic)
        )
        assert topic in pubsubs[0].peer_topics

        pubsubs[0].handle_subscription(
            peer_id, rpc_pb2.RPC.SubOpts(subscribe=False, topicid=topic)
        )
        assert topic not in pubsubs[0].peer_topics


@pytest.mark.trio
async def test_disconnect_removes_empty_topic_keys():
    async with PubsubFactory.create_batch_with_gossipsub(1) as pubsubs:
        peer_id = IDFactory()
        pubsub = pubsubs[0]
        for i in range(20):
            pubsub.handle_subscription(
                peer_id,
                rpc_pb2.RPC.SubOpts(subscribe=True, topicid=f"flood-topic-{i}"),
            )
        assert len(pubsub.peer_topics) == 20

        pubsub._clear_peer_from_all_topics(peer_id)
        assert len(pubsub.peer_topics) == 0
        assert peer_id not in pubsub._peer_subscription_count


@pytest.mark.trio
async def test_handle_dead_peer_removes_empty_topic_keys():
    async with PubsubFactory.create_batch_with_gossipsub(1) as pubsubs:
        peer_id = IDFactory()
        pubsub = pubsubs[0]
        pubsub.peers[peer_id] = cast(INetStream, object())

        for i in range(20):
            pubsub.handle_subscription(
                peer_id,
                rpc_pb2.RPC.SubOpts(subscribe=True, topicid=f"dead-peer-topic-{i}"),
            )
        assert len(pubsub.peer_topics) == 20

        pubsub._handle_dead_peer(peer_id)
        assert len(pubsub.peer_topics) == 0
        assert peer_id not in pubsub.peers
        assert peer_id not in pubsub._peer_subscription_count


@pytest.mark.trio
async def test_blacklist_clears_peer_topics():
    async with PubsubFactory.create_batch_with_gossipsub(2) as pubsubs:
        pubsub0, pubsub1 = pubsubs
        await connect(pubsub0.host, pubsub1.host)
        await pubsub0.wait_for_peer(pubsub1.my_id)

        pubsub0.handle_subscription(
            pubsub1.my_id,
            rpc_pb2.RPC.SubOpts(subscribe=True, topicid="blacklist-topic"),
        )
        assert "blacklist-topic" in pubsub0.peer_topics

        pubsub0.add_to_blacklist(pubsub1.my_id)
        with trio.fail_after(5.0):
            while pubsub1.my_id in pubsub0.peers:
                await trio.sleep(0.01)

        assert pubsub1.my_id not in pubsub0.peers
        assert "blacklist-topic" not in pubsub0.peer_topics


@pytest.mark.trio
async def test_stop_clears_subscription_state():
    async with PubsubFactory.create_batch_with_gossipsub(1) as pubsubs:
        peer_id = IDFactory()
        pubsub = pubsubs[0]
        pubsub.handle_subscription(
            peer_id, rpc_pb2.RPC.SubOpts(subscribe=True, topicid="shutdown-topic")
        )
        assert pubsub.peer_topics
        pubsub._clear_subscription_state()
        assert not pubsub.peer_topics
        assert not pubsub._peer_subscription_count


@pytest.mark.trio
async def test_allowed_topics_rejects_unlisted_subscribe():
    allowed = frozenset({"allowed-topic"})
    async with PubsubFactory.create_batch_with_gossipsub(
        1, allowed_topics=allowed
    ) as pubsubs:
        peer_id = IDFactory()
        pubsub = pubsubs[0]
        pubsub.handle_subscription(
            peer_id,
            rpc_pb2.RPC.SubOpts(subscribe=True, topicid="forbidden-topic"),
        )
        assert not pubsub.peer_topics

        pubsub.handle_subscription(
            peer_id,
            rpc_pb2.RPC.SubOpts(subscribe=True, topicid="allowed-topic"),
        )
        assert "allowed-topic" in pubsub.peer_topics


@pytest.mark.trio
async def test_allowed_topics_allows_unsubscribe():
    allowed = frozenset({"allowed-topic"})
    async with PubsubFactory.create_batch_with_gossipsub(
        1, allowed_topics=allowed
    ) as pubsubs:
        peer_id = IDFactory()
        pubsub = pubsubs[0]
        pubsub.handle_subscription(
            peer_id,
            rpc_pb2.RPC.SubOpts(subscribe=True, topicid="allowed-topic"),
        )
        pubsub.handle_subscription(
            peer_id,
            rpc_pb2.RPC.SubOpts(subscribe=False, topicid="allowed-topic"),
        )
        assert "allowed-topic" not in pubsub.peer_topics


@pytest.mark.trio
async def test_per_peer_subscription_limit_enforced():
    limit = 5
    async with PubsubFactory.create_batch_with_gossipsub(
        1, max_subscriptions_per_peer=limit
    ) as pubsubs:
        peer_id = IDFactory()
        pubsub = pubsubs[0]
        for i in range(limit):
            pubsub.handle_subscription(
                peer_id,
                rpc_pb2.RPC.SubOpts(subscribe=True, topicid=f"peer-topic-{i}"),
            )
        assert len(pubsub.peer_topics) == limit
        assert pubsub._peer_subscription_count[peer_id] == limit

        pubsub.handle_subscription(
            peer_id,
            rpc_pb2.RPC.SubOpts(subscribe=True, topicid="peer-topic-overflow"),
        )
        assert len(pubsub.peer_topics) == limit
        assert "peer-topic-overflow" not in pubsub.peer_topics


@pytest.mark.trio
async def test_resubscribe_same_topic_does_not_increment_count():
    async with PubsubFactory.create_batch_with_gossipsub(
        1, max_subscriptions_per_peer=2
    ) as pubsubs:
        peer_id = IDFactory()
        pubsub = pubsubs[0]
        topic = "repeat-topic"
        sub = rpc_pb2.RPC.SubOpts(subscribe=True, topicid=topic)
        pubsub.handle_subscription(peer_id, sub)
        pubsub.handle_subscription(peer_id, sub)
        assert pubsub._peer_subscription_count[peer_id] == 1

        pubsub.handle_subscription(
            peer_id, rpc_pb2.RPC.SubOpts(subscribe=True, topicid="other-topic")
        )
        assert pubsub._peer_subscription_count[peer_id] == 2

        pubsub.handle_subscription(
            peer_id,
            rpc_pb2.RPC.SubOpts(subscribe=True, topicid="third-topic-overflow"),
        )
        assert len(pubsub.peer_topics) == 2


@pytest.mark.trio
async def test_per_rpc_subscription_limit_rejected(nursery, security_protocol):
    limit = 3
    async with (
        PubsubFactory.create_batch_with_gossipsub(
            1,
            security_protocol=security_protocol,
            max_subscriptions_per_rpc=limit,
        ) as pubsubs,
        net_stream_pair_factory(security_protocol=security_protocol) as stream_pair,
    ):
        pubsub = pubsubs[0]
        nursery.start_soon(pubsub.continuously_read_stream, stream_pair[0])

        rpc = rpc_pb2.RPC(
            subscriptions=[
                rpc_pb2.RPC.SubOpts(subscribe=True, topicid=f"rpc-topic-{i}")
                for i in range(limit + 1)
            ]
        )
        await stream_pair[1].write(encode_varint_prefixed(rpc.SerializeToString()))
        await trio.sleep(0.1)

        assert len(pubsub.peer_topics) == 0


@pytest.mark.trio
async def test_per_rpc_subscription_at_limit_accepted(nursery, security_protocol):
    limit = 3
    async with (
        PubsubFactory.create_batch_with_gossipsub(
            1,
            security_protocol=security_protocol,
            max_subscriptions_per_rpc=limit,
        ) as pubsubs,
        net_stream_pair_factory(security_protocol=security_protocol) as stream_pair,
    ):
        pubsub = pubsubs[0]
        remote_peer_id = stream_pair[0].muxed_conn.peer_id
        nursery.start_soon(pubsub.continuously_read_stream, stream_pair[0])

        rpc = rpc_pb2.RPC(
            subscriptions=[
                rpc_pb2.RPC.SubOpts(subscribe=True, topicid=f"rpc-topic-{i}")
                for i in range(limit)
            ]
        )
        await stream_pair[1].write(encode_varint_prefixed(rpc.SerializeToString()))
        await trio.sleep(0.1)

        assert len(pubsub.peer_topics) == limit
        assert pubsub._peer_subscription_count[remote_peer_id] == limit


@pytest.mark.trio
async def test_inbound_rpc_oversize_rejected(nursery, security_protocol):
    max_size = 64
    async with (
        PubsubFactory.create_batch_with_gossipsub(
            1,
            security_protocol=security_protocol,
            max_inbound_rpc_size=max_size,
        ) as pubsubs,
        net_stream_pair_factory(security_protocol=security_protocol) as stream_pair,
    ):
        pubsub = pubsubs[0]
        peer_id = IDFactory()
        nursery.start_soon(pubsub.continuously_read_stream, stream_pair[0])

        pubsub.handle_subscription(
            peer_id, rpc_pb2.RPC.SubOpts(subscribe=True, topicid="existing")
        )
        topics_before = len(pubsub.peer_topics)

        oversized_payload = b"x" * (max_size + 1)
        await stream_pair[1].write(encode_varint_prefixed(oversized_payload))
        await trio.sleep(0.1)

        assert len(pubsub.peer_topics) == topics_before
