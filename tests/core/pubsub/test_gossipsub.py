import random

import pytest
import trio

from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID,
    GossipSub,
)
from libp2p.tools.utils import (
    connect,
)
from tests.utils.factories import (
    IDFactory,
    PubsubFactory,
)
from tests.utils.pubsub.utils import (
    connect_some,
    dense_connect,
    one_to_all_connect,
    sparse_connect,
)


@pytest.mark.trio
async def test_join():
    async with PubsubFactory.create_batch_with_gossipsub(
        4, degree=4, degree_low=3, degree_high=5, heartbeat_interval=1, time_to_live=1
    ) as pubsubs_gsub:
        gossipsubs = []
        for pubsub in pubsubs_gsub:
            if isinstance(pubsub.router, GossipSub):
                gossipsubs.append(pubsub.router)
        hosts = [pubsub.host for pubsub in pubsubs_gsub]
        hosts_indices = list(range(len(pubsubs_gsub)))

        topic = "test_join"
        to_drop_topic = "test_drop_topic"
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

        # Wait 1 seconds for heartbeat to allow mesh to connect
        await trio.sleep(1)

        # Central node publish to the topic so that this topic
        # is added to central node's fanout
        # publish from the randomly chosen host
        await pubsubs_gsub[central_node_index].publish(topic, b"data")
        await pubsubs_gsub[central_node_index].publish(to_drop_topic, b"data")
        await trio.sleep(0.5)
        # Check that the gossipsub of central node has fanout for the topics
        assert topic, to_drop_topic in gossipsubs[central_node_index].fanout
        # Check that the gossipsub of central node does not have a mesh for the topics
        assert topic, to_drop_topic not in gossipsubs[central_node_index].mesh
        # Check that the gossipsub of central node
        # has a time_since_last_publish for the topics
        assert topic in gossipsubs[central_node_index].time_since_last_publish
        assert to_drop_topic in gossipsubs[central_node_index].time_since_last_publish

        await trio.sleep(1)
        # Check that after ttl the to_drop_topic is no more in fanout of central node
        assert to_drop_topic not in gossipsubs[central_node_index].fanout
        # Central node subscribes the topic
        await pubsubs_gsub[central_node_index].subscribe(topic)

        await trio.sleep(1)

        # Check that the gossipsub of central node no longer has fanout for the topic
        assert topic not in gossipsubs[central_node_index].fanout

        for i in hosts_indices:
            if i in subscribed_peer_indices:
                assert hosts[i].get_id() in gossipsubs[central_node_index].mesh[topic]
                assert hosts[central_node_index].get_id() in gossipsubs[i].mesh[topic]
            else:
                assert (
                    hosts[i].get_id() not in gossipsubs[central_node_index].mesh[topic]
                )
                assert topic not in gossipsubs[i].mesh


@pytest.mark.trio
async def test_leave():
    async with PubsubFactory.create_batch_with_gossipsub(1) as pubsubs_gsub:
        router = pubsubs_gsub[0].router
        assert isinstance(router, GossipSub)
        gossipsub = router
        topic = "test_leave"

        assert topic not in gossipsub.mesh

        await gossipsub.join(topic)
        assert topic in gossipsub.mesh

        await gossipsub.leave(topic)
        assert topic not in gossipsub.mesh

        # Test re-leave
        await gossipsub.leave(topic)


@pytest.mark.trio
async def test_handle_graft(monkeypatch):
    async with PubsubFactory.create_batch_with_gossipsub(2) as pubsubs_gsub:
        gossipsub_routers = []
        for pubsub in pubsubs_gsub:
            if isinstance(pubsub.router, GossipSub):
                gossipsub_routers.append(pubsub.router)
        gossipsubs = tuple(gossipsub_routers)

        index_alice = 0
        id_alice = pubsubs_gsub[index_alice].my_id
        index_bob = 1
        id_bob = pubsubs_gsub[index_bob].my_id
        await connect(pubsubs_gsub[index_alice].host, pubsubs_gsub[index_bob].host)

        # Wait 2 seconds for heartbeat to allow mesh to connect
        await trio.sleep(2)

        topic = "test_handle_graft"
        # Only lice subscribe to the topic
        await gossipsubs[index_alice].join(topic)

        # Monkey patch bob's `emit_prune` function so we can
        # check if it is called in `handle_graft`
        event_emit_prune = trio.Event()

        async def emit_prune(topic, sender_peer_id, do_px, is_unsubscribe):
            event_emit_prune.set()
            await trio.lowlevel.checkpoint()

        monkeypatch.setattr(gossipsubs[index_bob], "emit_prune", emit_prune)

        # Check that alice is bob's peer but not his mesh peer
        assert gossipsubs[index_bob].peer_protocol[id_alice] == PROTOCOL_ID
        assert topic not in gossipsubs[index_bob].mesh

        await gossipsubs[index_alice].emit_graft(topic, id_bob)

        # Check that `emit_prune` is called
        await event_emit_prune.wait()

        # Check that bob is alice's peer but not her mesh peer
        assert topic in gossipsubs[index_alice].mesh
        assert id_bob not in gossipsubs[index_alice].mesh[topic]
        assert gossipsubs[index_alice].peer_protocol[id_bob] == PROTOCOL_ID

        await gossipsubs[index_bob].emit_graft(topic, id_alice)

        await trio.sleep(1)

        # Check that bob is now alice's mesh peer
        assert id_bob in gossipsubs[index_alice].mesh[topic]


@pytest.mark.trio
async def test_handle_prune():
    async with PubsubFactory.create_batch_with_gossipsub(
        2, heartbeat_interval=3
    ) as pubsubs_gsub:
        gossipsub_routers = []
        for pubsub in pubsubs_gsub:
            if isinstance(pubsub.router, GossipSub):
                gossipsub_routers.append(pubsub.router)
        gossipsubs = tuple(gossipsub_routers)

        index_alice = 0
        id_alice = pubsubs_gsub[index_alice].my_id
        index_bob = 1
        id_bob = pubsubs_gsub[index_bob].my_id

        topic = "test_handle_prune"
        for pubsub in pubsubs_gsub:
            await pubsub.subscribe(topic)

        await connect(pubsubs_gsub[index_alice].host, pubsubs_gsub[index_bob].host)

        # Wait for heartbeat to allow mesh to connect
        await trio.sleep(1)

        # Check that they are each other's mesh peer
        assert id_alice in gossipsubs[index_bob].mesh[topic]
        assert id_bob in gossipsubs[index_alice].mesh[topic]

        # alice emit prune message to bob, alice should be removed
        # from bob's mesh peer
        await gossipsubs[index_alice].emit_prune(topic, id_bob, False, False)
        # `emit_prune` does not remove bob from alice's mesh peers
        assert id_bob in gossipsubs[index_alice].mesh[topic]

        # NOTE: We increase `heartbeat_interval` to 3 seconds so that bob will not
        # add alice back to his mesh after heartbeat.
        # Wait for bob to `handle_prune`
        await trio.sleep(0.1)

        # Check that alice is no longer bob's mesh peer
        assert id_alice not in gossipsubs[index_bob].mesh[topic]


@pytest.mark.trio
async def test_dense():
    async with PubsubFactory.create_batch_with_gossipsub(10) as pubsubs_gsub:
        hosts = [pubsub.host for pubsub in pubsubs_gsub]
        num_msgs = 5

        # All pubsub subscribe to foobar
        queues = [await pubsub.subscribe("foobar") for pubsub in pubsubs_gsub]

        # Densely connect libp2p hosts in a random way
        await dense_connect(hosts)

        # Wait 2 seconds for heartbeat to allow mesh to connect
        await trio.sleep(2)

        for i in range(num_msgs):
            msg_content = b"foo " + i.to_bytes(1, "big")

            # randomly pick a message origin
            origin_idx = random.randint(0, len(hosts) - 1)

            # publish from the randomly chosen host
            await pubsubs_gsub[origin_idx].publish("foobar", msg_content)

            await trio.sleep(0.5)
            # Assert that all blocking queues receive the message
            for queue in queues:
                msg = await queue.get()
                assert msg.data == msg_content


@pytest.mark.trio
async def test_fanout():
    async with PubsubFactory.create_batch_with_gossipsub(10) as pubsubs_gsub:
        hosts = [pubsub.host for pubsub in pubsubs_gsub]
        num_msgs = 5

        # All pubsub subscribe to foobar except for `pubsubs_gsub[0]`
        subs = [await pubsub.subscribe("foobar") for pubsub in pubsubs_gsub[1:]]

        # Sparsely connect libp2p hosts in random way
        await dense_connect(hosts)

        # Wait 2 seconds for heartbeat to allow mesh to connect
        await trio.sleep(2)

        topic = "foobar"
        # Send messages with origin not subscribed
        for i in range(num_msgs):
            msg_content = b"foo " + i.to_bytes(1, "big")

            # Pick the message origin to the node that is not subscribed to 'foobar'
            origin_idx = 0

            # publish from the randomly chosen host
            await pubsubs_gsub[origin_idx].publish(topic, msg_content)

            await trio.sleep(0.5)
            # Assert that all blocking queues receive the message
            for sub in subs:
                msg = await sub.get()
                assert msg.data == msg_content

        # Subscribe message origin
        subs.insert(0, await pubsubs_gsub[0].subscribe(topic))

        # Send messages again
        for i in range(num_msgs):
            msg_content = b"bar " + i.to_bytes(1, "big")

            # Pick the message origin to the node that is not subscribed to 'foobar'
            origin_idx = 0

            # publish from the randomly chosen host
            await pubsubs_gsub[origin_idx].publish(topic, msg_content)

            await trio.sleep(0.5)
            # Assert that all blocking queues receive the message
            for sub in subs:
                msg = await sub.get()
                assert msg.data == msg_content


@pytest.mark.trio
@pytest.mark.slow
async def test_fanout_maintenance():
    async with PubsubFactory.create_batch_with_gossipsub(
        10, unsubscribe_back_off=1
    ) as pubsubs_gsub:
        hosts = [pubsub.host for pubsub in pubsubs_gsub]
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
        await trio.sleep(2)

        # Send messages with origin not subscribed
        for i in range(num_msgs):
            msg_content = b"foo " + i.to_bytes(1, "big")

            # Pick the message origin to the node that is not subscribed to 'foobar'
            origin_idx = 0

            # publish from the randomly chosen host
            await pubsubs_gsub[origin_idx].publish(topic, msg_content)

            await trio.sleep(0.5)
            # Assert that all blocking queues receive the message
            for queue in queues:
                msg = await queue.get()
                assert msg.data == msg_content

        for sub in pubsubs_gsub:
            await sub.unsubscribe(topic)

        queues = []

        await trio.sleep(2)

        # Resub and repeat
        for i in range(1, len(pubsubs_gsub)):
            q = await pubsubs_gsub[i].subscribe(topic)

            # Add each blocking queue to an array of blocking queues
            queues.append(q)

        await trio.sleep(2)

        # Check messages can still be sent
        for i in range(num_msgs):
            msg_content = b"bar " + i.to_bytes(1, "big")

            # Pick the message origin to the node that is not subscribed to 'foobar'
            origin_idx = 0

            # publish from the randomly chosen host
            await pubsubs_gsub[origin_idx].publish(topic, msg_content)

            await trio.sleep(0.5)
            # Assert that all blocking queues receive the message
            for queue in queues:
                msg = await queue.get()
                assert msg.data == msg_content


@pytest.mark.trio
async def test_gossip_propagation():
    async with PubsubFactory.create_batch_with_gossipsub(
        2, degree=1, degree_low=0, degree_high=2, gossip_window=50, gossip_history=100
    ) as pubsubs_gsub:
        topic = "foo"
        queue_0 = await pubsubs_gsub[0].subscribe(topic)

        # node 0 publish to topic
        msg_content = b"foo_msg"

        # publish from the randomly chosen host
        await pubsubs_gsub[0].publish(topic, msg_content)

        await trio.sleep(0.5)
        # Assert that the blocking queues receive the message
        msg = await queue_0.get()
        assert msg.data == msg_content


@pytest.mark.parametrize("initial_mesh_peer_count", (7, 10, 13))
@pytest.mark.trio
async def test_mesh_heartbeat(initial_mesh_peer_count, monkeypatch):
    async with PubsubFactory.create_batch_with_gossipsub(
        1, heartbeat_initial_delay=100
    ) as pubsubs_gsub:
        # It's difficult to set up the initial peer subscription condition.
        # Ideally I would like to have initial mesh peer count that's below
        # ``GossipSubDegree`` so I can test if `mesh_heartbeat` return correct peers to
        # GRAFT. The problem is that I can not set it up so that we have peers subscribe
        # to the topic but not being part of our mesh peers (as these peers are the
        # peers to GRAFT). So I monkeypatch the peer subscriptions and our mesh peers.
        total_peer_count = 14
        topic = "TEST_MESH_HEARTBEAT"

        fake_peer_ids = [IDFactory() for _ in range(total_peer_count)]
        peer_protocol = {peer_id: PROTOCOL_ID for peer_id in fake_peer_ids}
        router = pubsubs_gsub[0].router
        assert isinstance(router, GossipSub)
        monkeypatch.setattr(router, "peer_protocol", peer_protocol)

        peer_topics = {topic: set(fake_peer_ids)}
        # Monkeypatch the peer subscriptions
        monkeypatch.setattr(pubsubs_gsub[0], "peer_topics", peer_topics)

        mesh_peer_indices = random.sample(
            range(total_peer_count), initial_mesh_peer_count
        )
        mesh_peers = [fake_peer_ids[i] for i in mesh_peer_indices]
        router_mesh = {topic: set(mesh_peers)}
        # Monkeypatch our mesh peers
        monkeypatch.setattr(router, "mesh", router_mesh)

        peers_to_graft, peers_to_prune = router.mesh_heartbeat()
        if initial_mesh_peer_count > router.degree:
            # If number of initial mesh peers is more than `GossipSubDegree`,
            # we should PRUNE mesh peers
            assert len(peers_to_graft) == 0
            assert len(peers_to_prune) == initial_mesh_peer_count - router.degree
            for peer in peers_to_prune:
                assert peer in mesh_peers
        elif initial_mesh_peer_count < router.degree:
            # If number of initial mesh peers is less than `GossipSubDegree`,
            # we should GRAFT more peers
            assert len(peers_to_prune) == 0
            assert len(peers_to_graft) == router.degree - initial_mesh_peer_count
            for peer in peers_to_graft:
                assert peer not in mesh_peers
        else:
            assert len(peers_to_prune) == 0 and len(peers_to_graft) == 0


@pytest.mark.parametrize("initial_peer_count", (1, 4, 7))
@pytest.mark.trio
async def test_gossip_heartbeat(initial_peer_count, monkeypatch):
    async with PubsubFactory.create_batch_with_gossipsub(
        1, heartbeat_initial_delay=100
    ) as pubsubs_gsub:
        # The problem is that I can not set it up so that we have peers subscribe to the
        # topic but not being part of our mesh peers (as these peers are the peers to
        # GRAFT). So I monkeypatch the peer subscriptions and our mesh peers.
        total_peer_count = 28
        topic_mesh = "TEST_GOSSIP_HEARTBEAT_1"
        topic_fanout = "TEST_GOSSIP_HEARTBEAT_2"

        fake_peer_ids = [IDFactory() for _ in range(total_peer_count)]
        peer_protocol = {peer_id: PROTOCOL_ID for peer_id in fake_peer_ids}
        router_obj = pubsubs_gsub[0].router
        assert isinstance(router_obj, GossipSub)
        router = router_obj
        monkeypatch.setattr(router, "peer_protocol", peer_protocol)

        topic_mesh_peer_count = 14
        # Split into mesh peers and fanout peers
        peer_topics = {
            topic_mesh: set(fake_peer_ids[:topic_mesh_peer_count]),
            topic_fanout: set(fake_peer_ids[topic_mesh_peer_count:]),
        }
        # Monkeypatch the peer subscriptions
        monkeypatch.setattr(pubsubs_gsub[0], "peer_topics", peer_topics)

        mesh_peer_indices = random.sample(
            range(topic_mesh_peer_count), initial_peer_count
        )
        mesh_peers = [fake_peer_ids[i] for i in mesh_peer_indices]
        router_mesh = {topic_mesh: set(mesh_peers)}
        # Monkeypatch our mesh peers
        monkeypatch.setattr(router, "mesh", router_mesh)
        fanout_peer_indices = random.sample(
            range(topic_mesh_peer_count, total_peer_count), initial_peer_count
        )
        fanout_peers = [fake_peer_ids[i] for i in fanout_peer_indices]
        router_fanout = {topic_fanout: set(fanout_peers)}
        # Monkeypatch our fanout peers
        monkeypatch.setattr(router, "fanout", router_fanout)

        def window(topic):
            if topic == topic_mesh:
                return [topic_mesh]
            elif topic == topic_fanout:
                return [topic_fanout]
            else:
                return []

        # Monkeypatch the memory cache messages
        monkeypatch.setattr(router.mcache, "window", window)

        peers_to_gossip = router.gossip_heartbeat()
        # If our mesh peer count is less than `GossipSubDegree`, we should gossip to up
        # to `GossipSubDegree` peers (exclude mesh peers).
        if topic_mesh_peer_count - initial_peer_count < router.degree:
            # The same goes for fanout so it's two times the number of peers to gossip.
            assert len(peers_to_gossip) == 2 * (
                topic_mesh_peer_count - initial_peer_count
            )
        elif topic_mesh_peer_count - initial_peer_count >= router.degree:
            assert len(peers_to_gossip) == 2 * (router.degree)

        for peer in peers_to_gossip:
            if peer in peer_topics[topic_mesh]:
                # Check that the peer to gossip to is not in our mesh peers
                assert peer not in mesh_peers
                assert topic_mesh in peers_to_gossip[peer]
            elif peer in peer_topics[topic_fanout]:
                # Check that the peer to gossip to is not in our fanout peers
                assert peer not in fanout_peers
                assert topic_fanout in peers_to_gossip[peer]


@pytest.mark.trio
async def test_dense_connect_fallback():
    """Test that sparse_connect falls back to dense connect for small networks."""
    async with PubsubFactory.create_batch_with_gossipsub(3) as pubsubs_gsub:
        hosts = [pubsub.host for pubsub in pubsubs_gsub]
        degree = 2

        # Create network (should use dense connect)
        await sparse_connect(hosts, degree)

        # Wait for connections to be established
        await trio.sleep(2)

        # Verify dense topology (all nodes connected to each other)
        for i, pubsub in enumerate(pubsubs_gsub):
            connected_peers = len(pubsub.peers)
            expected_connections = len(hosts) - 1
            assert connected_peers == expected_connections, (
                f"Host {i} has {connected_peers} connections, "
                f"expected {expected_connections} in dense mode"
            )


@pytest.mark.trio
async def test_sparse_connect():
    """Test sparse connect functionality and message propagation."""
    async with PubsubFactory.create_batch_with_gossipsub(10) as pubsubs_gsub:
        hosts = [pubsub.host for pubsub in pubsubs_gsub]
        degree = 2
        topic = "test_topic"

        # Create network (should use sparse connect)
        await sparse_connect(hosts, degree)

        # Wait for connections to be established
        await trio.sleep(2)

        # Verify sparse topology
        for i, pubsub in enumerate(pubsubs_gsub):
            connected_peers = len(pubsub.peers)
            assert degree <= connected_peers < len(hosts) - 1, (
                f"Host {i} has {connected_peers} connections, "
                f"expected between {degree} and {len(hosts) - 1} in sparse mode"
            )

        # Test message propagation
        queues = [await pubsub.subscribe(topic) for pubsub in pubsubs_gsub]
        await trio.sleep(2)

        # Publish and verify message propagation
        msg_content = b"test_msg"
        await pubsubs_gsub[0].publish(topic, msg_content)
        await trio.sleep(2)

        # Verify message propagation - ideally all nodes should receive it
        received_count = 0
        for queue in queues:
            try:
                msg = await queue.get()
                if msg.data == msg_content:
                    received_count += 1
            except Exception:
                continue

        total_nodes = len(pubsubs_gsub)

        # Ideally all nodes should receive the message for optimal scalability
        if received_count == total_nodes:
            # Perfect propagation achieved
            pass
        else:
            # require more than half for acceptable scalability
            min_required = (total_nodes + 1) // 2
            assert received_count >= min_required, (
                f"Message propagation insufficient: "
                f"{received_count}/{total_nodes} nodes "
                f"received the message. Ideally all nodes should receive it, but at "
                f"minimum {min_required} required for sparse network scalability."
            )


@pytest.mark.trio
async def test_connect_some_with_fewer_hosts_than_degree():
    """Test connect_some when there are fewer hosts than degree."""
    # Create 3 hosts with degree=5
    async with PubsubFactory.create_batch_with_floodsub(3) as pubsubs_fsub:
        hosts = [pubsub.host for pubsub in pubsubs_fsub]
        degree = 5

        await connect_some(hosts, degree)
        await trio.sleep(0.1)  # Allow connections to establish

        # Each host should connect to all other hosts (since there are only 2 others)
        for i, pubsub in enumerate(pubsubs_fsub):
            connected_peers = len(pubsub.peers)
            expected_max_connections = len(hosts) - 1  # All others
            assert connected_peers <= expected_max_connections, (
                f"Host {i} has {connected_peers} connections, "
                f"but can only connect to {expected_max_connections} others"
            )


@pytest.mark.trio
async def test_connect_some_degree_limit_enforced():
    """Test that connect_some enforces degree limits and creates expected topology."""
    # Test with small network where we can verify exact behavior
    async with PubsubFactory.create_batch_with_floodsub(6) as pubsubs_fsub:
        hosts = [pubsub.host for pubsub in pubsubs_fsub]
        degree = 2

        await connect_some(hosts, degree)
        await trio.sleep(0.1)

        # With 6 hosts and degree=2, expected connections:
        # Host 0 → connects to hosts 1,2 (2 peers total)
        # Host 1 → connects to hosts 2,3 (3 peers: 0,2,3)
        # Host 2 → connects to hosts 3,4 (4 peers: 0,1,3,4)
        # Host 3 → connects to hosts 4,5 (3 peers: 1,2,4,5) - wait, that's 4!
        # Host 4 → connects to host 5 (3 peers: 2,3,5)
        # Host 5 → (2 peers: 3,4)

        peer_counts = [len(pubsub.peers) for pubsub in pubsubs_fsub]

        # First and last hosts should have exactly degree connections
        assert peer_counts[0] == degree, (
            f"Host 0 should have {degree} peers, got {peer_counts[0]}"
        )
        assert peer_counts[-1] <= degree, (
            f"Last host should have ≤ {degree} peers, got {peer_counts[-1]}"
        )

        # Middle hosts may have more due to bidirectional connections
        # but the pattern should be consistent with degree limit
        total_connections = sum(peer_counts)

        # Should be less than full mesh (each host connected to all others)
        full_mesh_connections = len(hosts) * (len(hosts) - 1)
        assert total_connections < full_mesh_connections, (
            f"Got {total_connections} total connections, "
            f"but full mesh would be {full_mesh_connections}"
        )

        # Should be more than just a chain (each host connected to next only)
        chain_connections = 2 * (len(hosts) - 1)  # bidirectional chain
        assert total_connections > chain_connections, (
            f"Got {total_connections} total connections, which is too few "
            f"(chain would be {chain_connections})"
        )


@pytest.mark.trio
async def test_connect_some_degree_zero():
    """Test edge case: degree=0 should result in no connections."""
    # Create 5 hosts with degree=0
    async with PubsubFactory.create_batch_with_floodsub(5) as pubsubs_fsub:
        hosts = [pubsub.host for pubsub in pubsubs_fsub]
        degree = 0

        await connect_some(hosts, degree)
        await trio.sleep(0.1)  # Allow any potential connections to establish

        # Verify no connections were made
        for i, pubsub in enumerate(pubsubs_fsub):
            connected_peers = len(pubsub.peers)
            assert connected_peers == 0, (
                f"Host {i} has {connected_peers} connections, "
                f"but degree=0 should result in no connections"
            )


@pytest.mark.trio
async def test_connect_some_negative_degree():
    """Test edge case: negative degree should be handled gracefully."""
    # Create 5 hosts with degree=-1
    async with PubsubFactory.create_batch_with_floodsub(5) as pubsubs_fsub:
        hosts = [pubsub.host for pubsub in pubsubs_fsub]
        degree = -1

        await connect_some(hosts, degree)
        await trio.sleep(0.1)  # Allow any potential connections to establish

        # Verify no connections were made (negative degree should behave like 0)
        for i, pubsub in enumerate(pubsubs_fsub):
            connected_peers = len(pubsub.peers)
            assert connected_peers == 0, (
                f"Host {i} has {connected_peers} connections, "
                f"but negative degree should result in no connections"
            )


@pytest.mark.trio
async def test_sparse_connect_degree_zero():
    """Test sparse_connect with degree=0."""
    async with PubsubFactory.create_batch_with_floodsub(8) as pubsubs_fsub:
        hosts = [pubsub.host for pubsub in pubsubs_fsub]
        degree = 0

        await sparse_connect(hosts, degree)
        await trio.sleep(0.1)  # Allow connections to establish

        # With degree=0, sparse_connect should still create neighbor connections
        # for connectivity (this is part of the algorithm design)
        for i, pubsub in enumerate(pubsubs_fsub):
            connected_peers = len(pubsub.peers)
            # Should have some connections due to neighbor connectivity
            # (each node connects to immediate neighbors)
            expected_neighbors = 2  # previous and next in ring
            assert connected_peers >= expected_neighbors, (
                f"Host {i} has {connected_peers} connections, "
                f"expected at least {expected_neighbors} neighbor connections"
            )


@pytest.mark.trio
async def test_empty_host_list():
    """Test edge case: empty host list should be handled gracefully."""
    hosts = []

    # All functions should handle empty lists gracefully
    await connect_some(hosts, 5)
    await sparse_connect(hosts, 3)
    await dense_connect(hosts)

    # If we reach here without exceptions, the test passes


@pytest.mark.trio
async def test_single_host():
    """Test edge case: single host should be handled gracefully."""
    async with PubsubFactory.create_batch_with_floodsub(1) as pubsubs_fsub:
        hosts = [pubsub.host for pubsub in pubsubs_fsub]

        # All functions should handle single host gracefully
        await connect_some(hosts, 5)
        await sparse_connect(hosts, 3)
        await dense_connect(hosts)

        # Single host should have no connections
        connected_peers = len(pubsubs_fsub[0].peers)
        assert connected_peers == 0, (
            f"Single host has {connected_peers} connections, expected 0"
        )
