"""Tests for pubsub subscription flood protections (GHSA-4f8r-922h-2vgv)."""

import pytest
import trio

from libp2p.pubsub.pb import rpc_pb2
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

        # Seed state so we can verify oversize frame does not add subscriptions.
        pubsub.handle_subscription(
            peer_id, rpc_pb2.RPC.SubOpts(subscribe=True, topicid="existing")
        )
        topics_before = len(pubsub.peer_topics)

        oversized_payload = b"x" * (max_size + 1)
        await stream_pair[1].write(encode_varint_prefixed(oversized_payload))
        await trio.sleep(0.1)

        assert len(pubsub.peer_topics) == topics_before
