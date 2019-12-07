import asyncio
import random

import pytest

from libp2p.peer.id import ID
from libp2p.tools.constants import GOSSIPSUB_PARAMS, GossipsubParams
from libp2p.tools.pubsub.utils import dense_connect, one_to_all_connect
from libp2p.tools.utils import connect


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


@pytest.mark.parametrize(
    "num_hosts, gossipsub_params", ((2, GossipsubParams(heartbeat_interval=3)),)
)
@pytest.mark.asyncio
async def test_handle_prune(pubsubs_gsub, hosts):
    gossipsubs = tuple(pubsub.router for pubsub in pubsubs_gsub)

    index_alice = 0
    id_alice = hosts[index_alice].get_id()
    index_bob = 1
    id_bob = hosts[index_bob].get_id()

    topic = "test_handle_prune"
    for pubsub in pubsubs_gsub:
        await pubsub.subscribe(topic)

    await connect(hosts[index_alice], hosts[index_bob])

    # Wait for heartbeat to allow mesh to connect
    await asyncio.sleep(1)

    # Check that they are each other's mesh peer
    assert id_alice in gossipsubs[index_bob].mesh[topic]
    assert id_bob in gossipsubs[index_alice].mesh[topic]

    # alice emit prune message to bob, alice should be removed
    # from bob's mesh peer
    await gossipsubs[index_alice].emit_prune(topic, id_bob)
    # `emit_prune` does not remove bob from alice's mesh peers
    assert id_bob in gossipsubs[index_alice].mesh[topic]

    # NOTE: We increase `heartbeat_interval` to 3 seconds so that bob will not
    # add alice back to his mesh after heartbeat.
    # Wait for bob to `handle_prune`
    await asyncio.sleep(0.1)

    # Check that alice is no longer bob's mesh peer
    assert id_alice not in gossipsubs[index_bob].mesh[topic]


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


@pytest.mark.parametrize(
    "num_hosts, gossipsub_params", ((1, GossipsubParams(heartbeat_initial_delay=100)),)
)
@pytest.mark.parametrize("initial_mesh_peer_count", (7, 10, 13))
@pytest.mark.asyncio
async def test_mesh_heartbeat(
    num_hosts, initial_mesh_peer_count, pubsubs_gsub, hosts, monkeypatch
):
    # It's difficult to set up the initial peer subscription condition.
    # Ideally I would like to have initial mesh peer count that's below ``GossipSubDegree``
    # so I can test if `mesh_heartbeat` return correct peers to GRAFT.
    # The problem is that I can not set it up so that we have peers subscribe to the topic
    # but not being part of our mesh peers (as these peers are the peers to GRAFT).
    # So I monkeypatch the peer subscriptions and our mesh peers.
    total_peer_count = 14
    topic = "TEST_MESH_HEARTBEAT"

    fake_peer_ids = [
        ID((i).to_bytes(2, byteorder="big")) for i in range(total_peer_count)
    ]
    monkeypatch.setattr(pubsubs_gsub[0].router, "peers_gossipsub", fake_peer_ids)

    peer_topics = {topic: fake_peer_ids}
    # Monkeypatch the peer subscriptions
    monkeypatch.setattr(pubsubs_gsub[0], "peer_topics", peer_topics)

    mesh_peer_indices = random.sample(range(total_peer_count), initial_mesh_peer_count)
    mesh_peers = [fake_peer_ids[i] for i in mesh_peer_indices]
    router_mesh = {topic: list(mesh_peers)}
    # Monkeypatch our mesh peers
    monkeypatch.setattr(pubsubs_gsub[0].router, "mesh", router_mesh)

    peers_to_graft, peers_to_prune = pubsubs_gsub[0].router.mesh_heartbeat()
    if initial_mesh_peer_count > GOSSIPSUB_PARAMS.degree:
        # If number of initial mesh peers is more than `GossipSubDegree`, we should PRUNE mesh peers
        assert len(peers_to_graft) == 0
        assert len(peers_to_prune) == initial_mesh_peer_count - GOSSIPSUB_PARAMS.degree
        for peer in peers_to_prune:
            assert peer in mesh_peers
    elif initial_mesh_peer_count < GOSSIPSUB_PARAMS.degree:
        # If number of initial mesh peers is less than `GossipSubDegree`, we should GRAFT more peers
        assert len(peers_to_prune) == 0
        assert len(peers_to_graft) == GOSSIPSUB_PARAMS.degree - initial_mesh_peer_count
        for peer in peers_to_graft:
            assert peer not in mesh_peers
    else:
        assert len(peers_to_prune) == 0 and len(peers_to_graft) == 0


@pytest.mark.parametrize(
    "num_hosts, gossipsub_params", ((1, GossipsubParams(heartbeat_initial_delay=100)),)
)
@pytest.mark.parametrize("initial_peer_count", (1, 4, 7))
@pytest.mark.asyncio
async def test_gossip_heartbeat(
    num_hosts, initial_peer_count, pubsubs_gsub, hosts, monkeypatch
):
    # The problem is that I can not set it up so that we have peers subscribe to the topic
    # but not being part of our mesh peers (as these peers are the peers to GRAFT).
    # So I monkeypatch the peer subscriptions and our mesh peers.
    total_peer_count = 28
    topic_mesh = "TEST_GOSSIP_HEARTBEAT_1"
    topic_fanout = "TEST_GOSSIP_HEARTBEAT_2"

    fake_peer_ids = [
        ID((i).to_bytes(2, byteorder="big")) for i in range(total_peer_count)
    ]
    monkeypatch.setattr(pubsubs_gsub[0].router, "peers_gossipsub", fake_peer_ids)

    topic_mesh_peer_count = 14
    # Split into mesh peers and fanout peers
    peer_topics = {
        topic_mesh: fake_peer_ids[:topic_mesh_peer_count],
        topic_fanout: fake_peer_ids[topic_mesh_peer_count:],
    }
    # Monkeypatch the peer subscriptions
    monkeypatch.setattr(pubsubs_gsub[0], "peer_topics", peer_topics)

    mesh_peer_indices = random.sample(range(topic_mesh_peer_count), initial_peer_count)
    mesh_peers = [fake_peer_ids[i] for i in mesh_peer_indices]
    router_mesh = {topic_mesh: list(mesh_peers)}
    # Monkeypatch our mesh peers
    monkeypatch.setattr(pubsubs_gsub[0].router, "mesh", router_mesh)
    fanout_peer_indices = random.sample(
        range(topic_mesh_peer_count, total_peer_count), initial_peer_count
    )
    fanout_peers = [fake_peer_ids[i] for i in fanout_peer_indices]
    router_fanout = {topic_fanout: list(fanout_peers)}
    # Monkeypatch our fanout peers
    monkeypatch.setattr(pubsubs_gsub[0].router, "fanout", router_fanout)

    def window(topic):
        if topic == topic_mesh:
            return [topic_mesh]
        elif topic == topic_fanout:
            return [topic_fanout]
        else:
            return []

    # Monkeypatch the memory cache messages
    monkeypatch.setattr(pubsubs_gsub[0].router.mcache, "window", window)

    peers_to_gossip = pubsubs_gsub[0].router.gossip_heartbeat()
    # If our mesh peer count is less than `GossipSubDegree`, we should gossip to up to
    # `GossipSubDegree` peers (exclude mesh peers).
    if topic_mesh_peer_count - initial_peer_count < GOSSIPSUB_PARAMS.degree:
        # The same goes for fanout so it's two times the number of peers to gossip.
        assert len(peers_to_gossip) == 2 * (topic_mesh_peer_count - initial_peer_count)
    elif topic_mesh_peer_count - initial_peer_count >= GOSSIPSUB_PARAMS.degree:
        assert len(peers_to_gossip) == 2 * (GOSSIPSUB_PARAMS.degree)

    for peer in peers_to_gossip:
        if peer in peer_topics[topic_mesh]:
            # Check that the peer to gossip to is not in our mesh peers
            assert peer not in mesh_peers
            assert topic_mesh in peers_to_gossip[peer]
        elif peer in peer_topics[topic_fanout]:
            # Check that the peer to gossip to is not in our fanout peers
            assert peer not in fanout_peers
            assert topic_fanout in peers_to_gossip[peer]
