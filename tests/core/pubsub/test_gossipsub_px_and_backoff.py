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
from tests.utils.pubsub.wait import wait_for


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
        await pubsubs[0].wait_for_peer(host_1.get_id())
        await pubsubs[1].wait_for_peer(host_0.get_id())

        # both join the topic
        await gsub0.join(topic)
        await gsub1.join(topic)
        await gsub0.emit_graft(topic, host_1.get_id())
        await pubsubs[1].wait_for_mesh(host_0.get_id(), topic)

        # ensure peer is registered in mesh
        assert host_0.get_id() in gsub1.mesh[topic]

        # prune host_1 from gsub0's mesh
        await gsub0.emit_prune(topic, host_1.get_id(), False, False)
        await wait_for(
            lambda: host_0.get_id() not in gsub1.mesh.get(topic, set()),
            fail_msg="peer should leave mesh after prune",
        )

        # host_0 should not be in gsub1's mesh
        assert host_0.get_id() not in gsub1.mesh[topic]

        # try to graft again immediately (should be rejected due to backoff)
        await gsub0.emit_graft(topic, host_1.get_id())
        # Negative-assert race window: allow rejected GRAFT/PRUNE to settle
        await trio.sleep(0.5)
        assert host_0.get_id() not in gsub1.mesh[topic], (
            "peer should be backoffed and not re-added"
        )

        # try to graft again (should succeed after backoff)
        await trio.sleep(2)  # prune_back_off expiry
        await gsub0.emit_graft(topic, host_1.get_id())
        await pubsubs[1].wait_for_mesh(host_0.get_id(), topic)
        assert host_0.get_id() in gsub1.mesh[topic], (
            "peer should be able to rejoin after backoff"
        )


@pytest.mark.trio
async def test_unsubscribe_backoff():
    async with PubsubFactory.create_batch_with_gossipsub(
        2, heartbeat_interval=0.5, prune_back_off=2, unsubscribe_back_off=4
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
        await pubsubs[0].wait_for_peer(host_1.get_id())
        await pubsubs[1].wait_for_peer(host_0.get_id())

        # both join the topic
        await gsub0.join(topic)
        await gsub1.join(topic)
        await gsub0.emit_graft(topic, host_1.get_id())
        await pubsubs[1].wait_for_mesh(host_0.get_id(), topic)

        # ensure peer is registered in mesh
        assert host_0.get_id() in gsub1.mesh[topic]

        # host_1 unsubscribes from the topic
        await gsub1.leave(topic)
        assert topic not in gsub1.mesh

        # host_1 resubscribes to the topic
        await gsub1.join(topic)
        assert topic in gsub1.mesh

        # try to graft again immediately (should be rejected due to backoff)
        await gsub0.emit_graft(topic, host_1.get_id())
        # Negative-assert race window: allow rejected GRAFT/PRUNE to settle
        await trio.sleep(0.5)
        assert host_0.get_id() not in gsub1.mesh[topic], (
            "peer should be backoffed and not re-added"
        )

        # try to graft again (should succeed after backoff)
        # Wait longer than unsubscribe_back_off (4 seconds) + some buffer
        await trio.sleep(4.5)
        await gsub0.emit_graft(topic, host_1.get_id())
        await pubsubs[1].wait_for_mesh(host_0.get_id(), topic)
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
        await connect(host_0, host_2)  # Add connection so host_0 knows about host_2
        for i, j in ((0, 1), (1, 2), (0, 2)):
            await pubsubs[i].wait_for_peer(pubsubs[j].my_id)
            await pubsubs[j].wait_for_peer(pubsubs[i].my_id)

        # all join the topic and 0 <-> 1 and 1 <-> 2 graft
        await pubsubs[1].subscribe(topic)
        await pubsubs[0].subscribe(topic)
        await pubsubs[2].subscribe(topic)
        for i, j in ((0, 1), (1, 2), (0, 2)):
            await pubsubs[i].wait_for_subscription(pubsubs[j].my_id, topic)
            await pubsubs[j].wait_for_subscription(pubsubs[i].my_id, topic)
        await gsub1.emit_graft(topic, host_0.get_id())
        await gsub1.emit_graft(topic, host_2.get_id())
        await gsub0.emit_graft(topic, host_1.get_id())
        await gsub2.emit_graft(topic, host_1.get_id())
        await pubsubs[1].wait_for_mesh(host_0.get_id(), topic)
        await pubsubs[1].wait_for_mesh(host_2.get_id(), topic)

        # ensure peer is registered in mesh
        assert host_0.get_id() in gsub1.mesh[topic]
        assert host_2.get_id() in gsub1.mesh[topic]

        # Disconnect host_0 and host_2 to simulate PX scenario
        await host_0.disconnect(host_2.get_id())
        await wait_for(
            lambda: host_2.get_id() not in pubsubs[0].peers,
            fail_msg="host_2 should leave pubsub peers after disconnect",
        )

        # Remove host_2 from host_0's mesh if it exists
        if host_2.get_id() in gsub0.mesh.get(topic, set()):
            gsub0.mesh[topic].discard(host_2.get_id())
        if host_0.get_id() in gsub2.mesh.get(topic, set()):
            gsub2.mesh[topic].discard(host_0.get_id())

        assert host_2.get_id() not in gsub0.mesh[topic]

        # host_1 unsubscribes from the topic
        await gsub1.leave(topic)
        assert topic not in gsub1.mesh

        # Wait for gsub0 to graft host_2 into its mesh via PX
        await pubsubs[0].wait_for_mesh(host_2.get_id(), topic)
        assert host_2.get_id() in gsub0.mesh[topic]


@pytest.mark.trio
async def test_topics_are_isolated():
    async with PubsubFactory.create_batch_with_gossipsub(
        2, heartbeat_interval=0.5, prune_back_off=2
    ) as pubsubs:
        gsub0 = pubsubs[0].router
        gsub1 = pubsubs[1].router
        assert isinstance(gsub0, GossipSub)
        assert isinstance(gsub1, GossipSub)
        host_0 = pubsubs[0].host
        host_1 = pubsubs[1].host

        topic1 = "test_prune_backoff"
        topic2 = "test_prune_backoff2"

        # connect hosts
        await connect(host_0, host_1)
        await pubsubs[0].wait_for_peer(host_1.get_id())
        await pubsubs[1].wait_for_peer(host_0.get_id())

        # both peers join both the topics
        await gsub0.join(topic1)
        await gsub1.join(topic1)
        await gsub0.join(topic2)
        await gsub1.join(topic2)
        await gsub0.emit_graft(topic1, host_1.get_id())
        await pubsubs[1].wait_for_mesh(host_0.get_id(), topic1)

        # ensure topic1 for peer is registered in mesh
        assert host_0.get_id() in gsub1.mesh[topic1]

        # prune topic1 for host_1 from gsub0's mesh
        await gsub0.emit_prune(topic1, host_1.get_id(), False, False)
        await wait_for(
            lambda: host_0.get_id() not in gsub1.mesh.get(topic1, set()),
            fail_msg="peer should leave topic1 mesh after prune",
        )

        # topic1 for host_0 should not be in gsub1's mesh
        assert host_0.get_id() not in gsub1.mesh[topic1]

        # try to regraft topic1 and graft new topic2
        await gsub0.emit_graft(topic1, host_1.get_id())
        await gsub0.emit_graft(topic2, host_1.get_id())
        await pubsubs[1].wait_for_mesh(host_0.get_id(), topic2)
        # Negative-assert race window for backoffed topic1
        await trio.sleep(0.5)
        assert host_0.get_id() not in gsub1.mesh[topic1], (
            "peer should be backoffed and not re-added"
        )
        assert host_0.get_id() in gsub1.mesh[topic2], (
            "peer should be able to join a different topic"
        )


@pytest.mark.trio
async def test_stress_churn():
    NUM_PEERS = 5
    CHURN_CYCLES = 30
    TOPIC = "stress_churn_topic"
    PRUNE_BACKOFF = 1
    HEARTBEAT_INTERVAL = 0.2

    async with PubsubFactory.create_batch_with_gossipsub(
        NUM_PEERS,
        heartbeat_interval=HEARTBEAT_INTERVAL,
        prune_back_off=PRUNE_BACKOFF,
    ) as pubsubs:
        routers: list[GossipSub] = []
        for ps in pubsubs:
            assert isinstance(ps.router, GossipSub)
            routers.append(ps.router)
        hosts = [ps.host for ps in pubsubs]

        # fully connect all peers
        for i in range(NUM_PEERS):
            for j in range(i + 1, NUM_PEERS):
                await connect(hosts[i], hosts[j])
        for i in range(NUM_PEERS):
            for j in range(i + 1, NUM_PEERS):
                await pubsubs[i].wait_for_peer(hosts[j].get_id())
                await pubsubs[j].wait_for_peer(hosts[i].get_id())

        # all peers join the topic
        for router in routers:
            await router.join(TOPIC)
        await wait_for(
            lambda: all(TOPIC in router.mesh for router in routers),
            fail_msg="all routers should have joined the topic",
        )

        # rapid join/prune cycles
        for cycle in range(CHURN_CYCLES):
            for i, router in enumerate(routers):
                # prune all other peers from this router's mesh
                for j, peer_host in enumerate(hosts):
                    if i != j:
                        await router.emit_prune(TOPIC, peer_host.get_id(), False, False)
            # Churn pacing between prune and graft bursts
            await trio.sleep(0.1)
            for i, router in enumerate(routers):
                # graft all other peers back
                for j, peer_host in enumerate(hosts):
                    if i != j:
                        await router.emit_graft(TOPIC, peer_host.get_id())
            # Churn pacing between cycles
            await trio.sleep(0.1)

        # wait for backoff entries to expire and cleanup
        await trio.sleep(PRUNE_BACKOFF * 2)

        # check that the backoff table is not unbounded
        for router in routers:
            # backoff is a dict: topic -> peer -> expiry
            backoff = getattr(router, "back_off", None)
            assert backoff is not None, "router missing backoff table"
            # only a small number of entries should remain (ideally 0)
            total_entries = sum(len(peers) for peers in backoff.values())
            assert total_entries < NUM_PEERS * 2, (
                f"backoff table grew too large: {total_entries} entries"
            )
