import asyncio
import random

import pytest

from tests.utils import cleanup, connect

from .configs import GossipsubParams
from .utils import dense_connect, one_to_all_connect


@pytest.mark.parametrize(
    "num_hosts, gossipsub_params",
    ((4, GossipsubParams(degree=4, degree_low=3, degree_high=5)),),
)
@pytest.mark.asyncio
async def test_join(num_hosts, hosts, pubsubs_gsub):
    gossipsubs = tuple(pubsub.router for pubsub in pubsubs_gsub)
    hosts_indices = list(range(num_hosts))

    topic = "test_join"
    central_node_index = 0
    # Remove index of central host from the indices
    hosts_indices.remove(central_node_index)
    num_subscribed_peer = 2
    subscribed_peer_indices = random.sample(hosts_indices, num_subscribed_peer)

    # All pubsub except the one of central node subscribe to topic
    for i in subscribed_peer_indices:
        await pubsubs_gsub[i].subscribe(topic)

    # Connect central host to all other hosts
    await one_to_all_connect(hosts, central_node_index)

    # Wait 2 seconds for heartbeat to allow mesh to connect
    await asyncio.sleep(2)

    # Central node publish to the topic so that this topic
    # is added to central node's fanout
    # publish from the randomly chosen host
    await pubsubs_gsub[central_node_index].publish(topic, b"data")

    # Check that the gossipsub of central node has fanout for the topic
    assert topic in gossipsubs[central_node_index].fanout
    # Check that the gossipsub of central node does not have a mesh for the topic
    assert topic not in gossipsubs[central_node_index].mesh

    # Central node subscribes the topic
    await pubsubs_gsub[central_node_index].subscribe(topic)

    await asyncio.sleep(2)

    # Check that the gossipsub of central node no longer has fanout for the topic
    assert topic not in gossipsubs[central_node_index].fanout

    for i in hosts_indices:
        if i in subscribed_peer_indices:
            assert hosts[i].get_id() in gossipsubs[central_node_index].mesh[topic]
            assert hosts[central_node_index].get_id() in gossipsubs[i].mesh[topic]
        else:
            assert hosts[i].get_id() not in gossipsubs[central_node_index].mesh[topic]
            assert topic not in gossipsubs[i].mesh

    await cleanup()


@pytest.mark.parametrize("num_hosts", (1,))
@pytest.mark.asyncio
async def test_leave(pubsubs_gsub):
    gossipsub = pubsubs_gsub[0].router
    topic = "test_leave"

    assert topic not in gossipsub.mesh

    await gossipsub.join(topic)
    assert topic in gossipsub.mesh

    await gossipsub.leave(topic)
    assert topic not in gossipsub.mesh

    # Test re-leave
    await gossipsub.leave(topic)

    await cleanup()


@pytest.mark.parametrize("num_hosts", (2,))
@pytest.mark.asyncio
async def test_handle_graft(pubsubs_gsub, hosts, event_loop, monkeypatch):
    gossipsubs = tuple(pubsub.router for pubsub in pubsubs_gsub)

    index_alice = 0
    id_alice = hosts[index_alice].get_id()
    index_bob = 1
    id_bob = hosts[index_bob].get_id()
    await connect(hosts[index_alice], hosts[index_bob])

    # Wait 2 seconds for heartbeat to allow mesh to connect
    await asyncio.sleep(2)

    topic = "test_handle_graft"
    # Only lice subscribe to the topic
    await gossipsubs[index_alice].join(topic)

    # Monkey patch bob's `emit_prune` function so we can
    # check if it is called in `handle_graft`
    event_emit_prune = asyncio.Event()

    async def emit_prune(topic, sender_peer_id):
        event_emit_prune.set()

    monkeypatch.setattr(gossipsubs[index_bob], "emit_prune", emit_prune)

    # Check that alice is bob's peer but not his mesh peer
    assert id_alice in gossipsubs[index_bob].peers_gossipsub
    assert topic not in gossipsubs[index_bob].mesh

    await gossipsubs[index_alice].emit_graft(topic, id_bob)

    # Check that `emit_prune` is called
    await asyncio.wait_for(event_emit_prune.wait(), timeout=1, loop=event_loop)
    assert event_emit_prune.is_set()

    # Check that bob is alice's peer but not her mesh peer
    assert topic in gossipsubs[index_alice].mesh
    assert id_bob not in gossipsubs[index_alice].mesh[topic]
    assert id_bob in gossipsubs[index_alice].peers_gossipsub

    await gossipsubs[index_bob].emit_graft(topic, id_alice)

    await asyncio.sleep(1)

    # Check that bob is now alice's mesh peer
    assert id_bob in gossipsubs[index_alice].mesh[topic]

    await cleanup()


@pytest.mark.parametrize(
    "num_hosts, gossipsub_params", ((2, GossipsubParams(heartbeat_interval=3)),)
)
@pytest.mark.asyncio
async def test_handle_prune(pubsubs_gsub, hosts, gossipsubs):
    index_alice = 0
    id_alice = hosts[index_alice].get_id()
    index_bob = 1
    id_bob = hosts[index_bob].get_id()

    topic = "test_handle_prune"
    for pubsub in pubsubs_gsub:
        await pubsub.subscribe(topic)

    await connect(hosts[index_alice], hosts[index_bob])

    # Wait 3 seconds for heartbeat to allow mesh to connect
    await asyncio.sleep(3)

    # Check that they are each other's mesh peer
    assert id_alice in gossipsubs[index_bob].mesh[topic]
    assert id_bob in gossipsubs[index_alice].mesh[topic]

    # alice emit prune message to bob, alice should be removed
    # from bob's mesh peer
    await gossipsubs[index_alice].emit_prune(topic, id_bob)

    # FIXME: This test currently works because the heartbeat interval
    # is increased to 3 seconds, so alice won't get add back into
    # bob's mesh peer during heartbeat.
    await asyncio.sleep(1)

    # Check that alice is no longer bob's mesh peer
    assert id_alice not in gossipsubs[index_bob].mesh[topic]
    assert id_bob in gossipsubs[index_alice].mesh[topic]

    await cleanup()


@pytest.mark.parametrize("num_hosts", (10,))
@pytest.mark.asyncio
async def test_dense(num_hosts, pubsubs_gsub, hosts):
    num_msgs = 5

    # All pubsub subscribe to foobar
    queues = []
    for pubsub in pubsubs_gsub:
        q = await pubsub.subscribe("foobar")

        # Add each blocking queue to an array of blocking queues
        queues.append(q)

    # Densely connect libp2p hosts in a random way
    await dense_connect(hosts)

    # Wait 2 seconds for heartbeat to allow mesh to connect
    await asyncio.sleep(2)

    for i in range(num_msgs):
        msg_content = b"foo " + i.to_bytes(1, "big")

        # randomly pick a message origin
        origin_idx = random.randint(0, num_hosts - 1)

        # publish from the randomly chosen host
        await pubsubs_gsub[origin_idx].publish("foobar", msg_content)

        await asyncio.sleep(0.5)
        # Assert that all blocking queues receive the message
        for queue in queues:
            msg = await queue.get()
            assert msg.data == msg_content
    await cleanup()


@pytest.mark.parametrize("num_hosts", (10,))
@pytest.mark.asyncio
async def test_fanout(hosts, pubsubs_gsub):
    num_msgs = 5

    # All pubsub subscribe to foobar except for `pubsubs_gsub[0]`
    queues = []
    for i in range(1, len(pubsubs_gsub)):
        q = await pubsubs_gsub[i].subscribe("foobar")

        # Add each blocking queue to an array of blocking queues
        queues.append(q)

    # Sparsely connect libp2p hosts in random way
    await dense_connect(hosts)

    # Wait 2 seconds for heartbeat to allow mesh to connect
    await asyncio.sleep(2)

    topic = "foobar"
    # Send messages with origin not subscribed
    for i in range(num_msgs):
        msg_content = b"foo " + i.to_bytes(1, "big")

        # Pick the message origin to the node that is not subscribed to 'foobar'
        origin_idx = 0

        # publish from the randomly chosen host
        await pubsubs_gsub[origin_idx].publish(topic, msg_content)

        await asyncio.sleep(0.5)
        # Assert that all blocking queues receive the message
        for queue in queues:
            msg = await queue.get()
            assert msg.data == msg_content

    # Subscribe message origin
    queues.insert(0, await pubsubs_gsub[0].subscribe(topic))

    # Send messages again
    for i in range(num_msgs):
        msg_content = b"bar " + i.to_bytes(1, "big")

        # Pick the message origin to the node that is not subscribed to 'foobar'
        origin_idx = 0

        # publish from the randomly chosen host
        await pubsubs_gsub[origin_idx].publish(topic, msg_content)

        await asyncio.sleep(0.5)
        # Assert that all blocking queues receive the message
        for queue in queues:
            msg = await queue.get()
            assert msg.data == msg_content

    await cleanup()


@pytest.mark.parametrize("num_hosts", (10,))
@pytest.mark.asyncio
@pytest.mark.slow
async def test_fanout_maintenance(hosts, pubsubs_gsub):
    num_msgs = 5

    # All pubsub subscribe to foobar
    queues = []
    topic = "foobar"
    for i in range(1, len(pubsubs_gsub)):
        q = await pubsubs_gsub[i].subscribe(topic)

        # Add each blocking queue to an array of blocking queues
        queues.append(q)

    # Sparsely connect libp2p hosts in random way
    await dense_connect(hosts)

    # Wait 2 seconds for heartbeat to allow mesh to connect
    await asyncio.sleep(2)

    # Send messages with origin not subscribed
    for i in range(num_msgs):
        msg_content = b"foo " + i.to_bytes(1, "big")

        # Pick the message origin to the node that is not subscribed to 'foobar'
        origin_idx = 0

        # publish from the randomly chosen host
        await pubsubs_gsub[origin_idx].publish(topic, msg_content)

        await asyncio.sleep(0.5)
        # Assert that all blocking queues receive the message
        for queue in queues:
            msg = await queue.get()
            assert msg.data == msg_content

    for sub in pubsubs_gsub:
        await sub.unsubscribe(topic)

    queues = []

    await asyncio.sleep(2)

    # Resub and repeat
    for i in range(1, len(pubsubs_gsub)):
        q = await pubsubs_gsub[i].subscribe(topic)

        # Add each blocking queue to an array of blocking queues
        queues.append(q)

    await asyncio.sleep(2)

    # Check messages can still be sent
    for i in range(num_msgs):
        msg_content = b"bar " + i.to_bytes(1, "big")

        # Pick the message origin to the node that is not subscribed to 'foobar'
        origin_idx = 0

        # publish from the randomly chosen host
        await pubsubs_gsub[origin_idx].publish(topic, msg_content)

        await asyncio.sleep(0.5)
        # Assert that all blocking queues receive the message
        for queue in queues:
            msg = await queue.get()
            assert msg.data == msg_content

    await cleanup()


@pytest.mark.parametrize(
    "num_hosts, gossipsub_params",
    (
        (
            2,
            GossipsubParams(
                degree=1,
                degree_low=0,
                degree_high=2,
                gossip_window=50,
                gossip_history=100,
            ),
        ),
    ),
)
@pytest.mark.asyncio
async def test_gossip_propagation(hosts, pubsubs_gsub):
    topic = "foo"
    await pubsubs_gsub[0].subscribe(topic)

    # node 0 publish to topic
    msg_content = b"foo_msg"

    # publish from the randomly chosen host
    await pubsubs_gsub[0].publish(topic, msg_content)

    # now node 1 subscribes
    queue_1 = await pubsubs_gsub[1].subscribe(topic)

    await connect(hosts[0], hosts[1])

    # wait for gossip heartbeat
    await asyncio.sleep(2)

    # should be able to read message
    msg = await queue_1.get()
    assert msg.data == msg_content

    await cleanup()
