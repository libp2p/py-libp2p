import pytest
import trio

from libp2p.pubsub.gossipsub import (
    GossipSub,
)
from libp2p.tools.utils import (
    connect,
)
from tests.utils.factories import (
    PubsubFactory,
)


@pytest.mark.trio
async def test_prune_backoff():
    async with PubsubFactory.create_batch_with_gossipsub(
        2, heartbeat_interval=0.5, prune_back_off=2
    ) as pubsubs:
        gsub0 = pubsubs[0].router
        gsub1 = pubsubs[1].router
        assert isinstance(gsub0, GossipSub)
        assert isinstance(gsub1, GossipSub)
        host_0 = pubsubs[0].host
        host_1 = pubsubs[1].host

        topic = "test_prune_backoff"

        # connect hosts
        await connect(host_0, host_1)
        await trio.sleep(0.5)

        # both join the topic
        await gsub0.join(topic)
        await gsub1.join(topic)
        await gsub0.emit_graft(topic, host_1.get_id())
        await trio.sleep(0.5)

        # ensure peer is registered in mesh
        assert host_0.get_id() in gsub1.mesh[topic]

        # prune host_1 from gsub0's mesh
        await gsub0.emit_prune(topic, host_1.get_id(), False, False)
        await trio.sleep(0.5)

        # host_0 should not be in gsub1's mesh
        assert host_0.get_id() not in gsub1.mesh[topic]

        # try to graft again immediately (should be rejected due to backoff)
        await gsub0.emit_graft(topic, host_1.get_id())
        await trio.sleep(0.5)
        assert host_0.get_id() not in gsub1.mesh[topic], (
            "peer should be backoffed and not re-added"
        )

        # try to graft again (should succeed after backoff)
        await trio.sleep(2)
        await gsub0.emit_graft(topic, host_1.get_id())
        await trio.sleep(1)
        assert host_0.get_id() in gsub1.mesh[topic], (
            "peer should be able to rejoin after backoff"
        )


@pytest.mark.trio
async def test_unsubscribe_backoff():
    async with PubsubFactory.create_batch_with_gossipsub(
        2, heartbeat_interval=1, prune_back_off=1, unsubscribe_back_off=2
    ) as pubsubs:
        gsub0 = pubsubs[0].router
        gsub1 = pubsubs[1].router
        assert isinstance(gsub0, GossipSub)
        assert isinstance(gsub1, GossipSub)
        host_0 = pubsubs[0].host
        host_1 = pubsubs[1].host

        topic = "test_unsubscribe_backoff"

        # connect hosts
        await connect(host_0, host_1)
        await trio.sleep(0.5)

        # both join the topic
        await gsub0.join(topic)
        await gsub1.join(topic)
        await gsub0.emit_graft(topic, host_1.get_id())
        await trio.sleep(0.5)

        # ensure peer is registered in mesh
        assert host_0.get_id() in gsub1.mesh[topic]

        # host_1 unsubscribes from the topic
        await gsub1.leave(topic)
        await trio.sleep(0.5)
        assert topic not in gsub1.mesh

        # host_1 resubscribes to the topic
        await gsub1.join(topic)
        await trio.sleep(0.5)
        assert topic in gsub1.mesh

        # try to graft again immediately (should be rejected due to backoff)
        await gsub0.emit_graft(topic, host_1.get_id())
        await trio.sleep(0.5)
        assert host_0.get_id() not in gsub1.mesh[topic], (
            "peer should be backoffed and not re-added"
        )

        # try to graft again (should succeed after backoff)
        await trio.sleep(1)
        await gsub0.emit_graft(topic, host_1.get_id())
        await trio.sleep(1)
        assert host_0.get_id() in gsub1.mesh[topic], (
            "peer should be able to rejoin after backoff"
        )


@pytest.mark.trio
async def test_peer_exchange():
    async with PubsubFactory.create_batch_with_gossipsub(
        3,
        heartbeat_interval=0.5,
        do_px=True,
        px_peers_count=1,
    ) as pubsubs:
        gsub0 = pubsubs[0].router
        gsub1 = pubsubs[1].router
        gsub2 = pubsubs[2].router
        assert isinstance(gsub0, GossipSub)
        assert isinstance(gsub1, GossipSub)
        assert isinstance(gsub2, GossipSub)
        host_0 = pubsubs[0].host
        host_1 = pubsubs[1].host
        host_2 = pubsubs[2].host

        topic = "test_peer_exchange"

        # connect hosts
        await connect(host_1, host_0)
        await connect(host_1, host_2)
        await trio.sleep(0.5)

        # all join the topic and 0 <-> 1 and 1 <-> 2 graft
        await pubsubs[1].subscribe(topic)
        await pubsubs[0].subscribe(topic)
        await pubsubs[2].subscribe(topic)
        await gsub1.emit_graft(topic, host_0.get_id())
        await gsub1.emit_graft(topic, host_2.get_id())
        await gsub0.emit_graft(topic, host_1.get_id())
        await gsub2.emit_graft(topic, host_1.get_id())
        await trio.sleep(1)

        # ensure peer is registered in mesh
        assert host_0.get_id() in gsub1.mesh[topic]
        assert host_2.get_id() in gsub1.mesh[topic]
        assert host_2.get_id() not in gsub0.mesh[topic]

        # host_1 unsubscribes from the topic
        await gsub1.leave(topic)
        await trio.sleep(1)  # Wait for heartbeat to update mesh
        assert topic not in gsub1.mesh

        # Wait for gsub0 to graft host_2 into its mesh via PX
        await trio.sleep(1)
        assert host_2.get_id() in gsub0.mesh[topic]
