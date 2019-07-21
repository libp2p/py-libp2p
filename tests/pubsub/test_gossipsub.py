import asyncio
import pytest
import random

from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.pubsub import Pubsub
from utils import message_id_generator, generate_RPC_packet, \
    create_libp2p_hosts, create_pubsub_and_gossipsub_instances, sparse_connect, dense_connect, \
    connect
from tests.utils import cleanup

SUPPORTED_PROTOCOLS = ["/gossipsub/1.0.0"]


@pytest.mark.asyncio
async def test_join():
    num_hosts = 1
    libp2p_hosts = await create_libp2p_hosts(num_hosts)

    # Create pubsub, gossipsub instances
    _, gossipsubs = create_pubsub_and_gossipsub_instances(libp2p_hosts, \
                                                                SUPPORTED_PROTOCOLS, \
                                                                10, 9, 11, 30, 3, 5, 0.5)

    gossipsub = gossipsubs[0]
    topic = "test_join"

    assert topic not in gossipsub.mesh
    await gossipsub.join(topic)
    assert topic in gossipsub.mesh

    # Test re-join
    await gossipsub.join(topic)

    await cleanup()


@pytest.mark.asyncio
async def test_leave():
    num_hosts = 1
    libp2p_hosts = await create_libp2p_hosts(num_hosts)

    # Create pubsub, gossipsub instances
    _, gossipsubs = create_pubsub_and_gossipsub_instances(libp2p_hosts, \
                                                                SUPPORTED_PROTOCOLS, \
                                                                10, 9, 11, 30, 3, 5, 0.5)

    gossipsub = gossipsubs[0]
    topic = "test_leave"

    await gossipsub.join(topic)
    assert topic in gossipsub.mesh

    await gossipsub.leave(topic)
    assert topic not in gossipsub.mesh

    # Test re-leave
    await gossipsub.leave(topic)

    await cleanup()


@pytest.mark.asyncio
async def test_dense():
    # Create libp2p hosts
    next_msg_id_func = message_id_generator(0)

    num_hosts = 10
    num_msgs = 5
    libp2p_hosts = await create_libp2p_hosts(num_hosts)

    # Create pubsub, gossipsub instances
    pubsubs, gossipsubs = create_pubsub_and_gossipsub_instances(libp2p_hosts, \
                                                                SUPPORTED_PROTOCOLS, \
                                                                10, 9, 11, 30, 3, 5, 0.5)

    # All pubsub subscribe to foobar
    queues = []
    for pubsub in pubsubs:
        q = await pubsub.subscribe("foobar")

        # Add each blocking queue to an array of blocking queues
        queues.append(q)

    # Sparsely connect libp2p hosts in random way
    await dense_connect(libp2p_hosts)

    # Wait 2 seconds for heartbeat to allow mesh to connect
    await asyncio.sleep(2)

    for i in range(num_msgs):
        msg_content = "foo " + str(i)

        # randomly pick a message origin
        origin_idx = random.randint(0, num_hosts - 1)
        origin_host = libp2p_hosts[origin_idx]
        host_id = str(origin_host.get_id())

        # Generate message packet
        packet = generate_RPC_packet(host_id, ["foobar"], msg_content, next_msg_id_func())

        # publish from the randomly chosen host
        await gossipsubs[origin_idx].publish(host_id, packet.SerializeToString())

        await asyncio.sleep(0.5)
        # Assert that all blocking queues receive the message
        items = []
        for queue in queues:
            msg = await queue.get()
            assert msg.data == packet.publish[0].data
            items.append(msg.data)
    await cleanup()

@pytest.mark.asyncio
async def test_fanout():
    # Create libp2p hosts
    next_msg_id_func = message_id_generator(0)

    num_hosts = 10
    num_msgs = 5
    libp2p_hosts = await create_libp2p_hosts(num_hosts)

    # Create pubsub, gossipsub instances
    pubsubs, gossipsubs = create_pubsub_and_gossipsub_instances(libp2p_hosts, \
                                                                SUPPORTED_PROTOCOLS, \
                                                                10, 9, 11, 30, 3, 5, 0.5)

    # All pubsub subscribe to foobar
    queues = []
    for i in range(1, len(pubsubs)):
        q = await pubsubs[i].subscribe("foobar")

        # Add each blocking queue to an array of blocking queues
        queues.append(q)

    # Sparsely connect libp2p hosts in random way
    await dense_connect(libp2p_hosts)

    # Wait 2 seconds for heartbeat to allow mesh to connect
    await asyncio.sleep(2)

    # Send messages with origin not subscribed
    for i in range(num_msgs):
        msg_content = "foo " + str(i)

        # Pick the message origin to the node that is not subscribed to 'foobar'
        origin_idx = 0
        origin_host = libp2p_hosts[origin_idx]
        host_id = str(origin_host.get_id())

        # Generate message packet
        packet = generate_RPC_packet(host_id, ["foobar"], msg_content, next_msg_id_func())

        # publish from the randomly chosen host
        await gossipsubs[origin_idx].publish(host_id, packet.SerializeToString())

        await asyncio.sleep(0.5)
        # Assert that all blocking queues receive the message
        for queue in queues:
            msg = await queue.get()
            assert msg.SerializeToString() == packet.publish[0].SerializeToString()

    # Subscribe message origin
    queues.append(await pubsubs[0].subscribe("foobar"))

    # Send messages again
    for i in range(num_msgs):
        msg_content = "foo " + str(i)

        # Pick the message origin to the node that is not subscribed to 'foobar'
        origin_idx = 0
        origin_host = libp2p_hosts[origin_idx]
        host_id = str(origin_host.get_id())

        # Generate message packet
        packet = generate_RPC_packet(host_id, ["foobar"], msg_content, next_msg_id_func())

        # publish from the randomly chosen host
        await gossipsubs[origin_idx].publish(host_id, packet.SerializeToString())

        await asyncio.sleep(0.5)
        # Assert that all blocking queues receive the message
        for queue in queues:
            msg = await queue.get()
            assert msg.SerializeToString() == packet.publish[0].SerializeToString()

    await cleanup()

@pytest.mark.asyncio
async def test_fanout_maintenance():
    # Create libp2p hosts
    next_msg_id_func = message_id_generator(0)

    num_hosts = 10
    num_msgs = 5
    libp2p_hosts = await create_libp2p_hosts(num_hosts)

    # Create pubsub, gossipsub instances
    pubsubs, gossipsubs = create_pubsub_and_gossipsub_instances(libp2p_hosts, \
                                                                SUPPORTED_PROTOCOLS, \
                                                                10, 9, 11, 30, 3, 5, 0.5)

    # All pubsub subscribe to foobar
    queues = []
    for i in range(1, len(pubsubs)):
        q = await pubsubs[i].subscribe("foobar")

        # Add each blocking queue to an array of blocking queues
        queues.append(q)

    # Sparsely connect libp2p hosts in random way
    await dense_connect(libp2p_hosts)

    # Wait 2 seconds for heartbeat to allow mesh to connect
    await asyncio.sleep(2)

    # Send messages with origin not subscribed
    for i in range(num_msgs):
        msg_content = "foo " + str(i)

        # Pick the message origin to the node that is not subscribed to 'foobar'
        origin_idx = 0
        origin_host = libp2p_hosts[origin_idx]
        host_id = str(origin_host.get_id())

        # Generate message packet
        packet = generate_RPC_packet(host_id, ["foobar"], msg_content, next_msg_id_func())

        # publish from the randomly chosen host
        await gossipsubs[origin_idx].publish(host_id, packet.SerializeToString())

        await asyncio.sleep(0.5)
        # Assert that all blocking queues receive the message
        for queue in queues:
            msg = await queue.get()
            assert msg.SerializeToString() == packet.publish[0].SerializeToString()

    for sub in pubsubs:
        await sub.unsubscribe('foobar')

    queues = []

    await asyncio.sleep(2)

    # Resub and repeat
    for i in range(1, len(pubsubs)):
        q = await pubsubs[i].subscribe("foobar")

        # Add each blocking queue to an array of blocking queues
        queues.append(q)

    await asyncio.sleep(2)

    # Check messages can still be sent
    for i in range(num_msgs):
        msg_content = "foo " + str(i)

        # Pick the message origin to the node that is not subscribed to 'foobar'
        origin_idx = 0
        origin_host = libp2p_hosts[origin_idx]
        host_id = str(origin_host.get_id())

        # Generate message packet
        packet = generate_RPC_packet(host_id, ["foobar"], msg_content, next_msg_id_func())

        # publish from the randomly chosen host
        await gossipsubs[origin_idx].publish(host_id, packet.SerializeToString())

        await asyncio.sleep(0.5)
        # Assert that all blocking queues receive the message
        for queue in queues:
            msg = await queue.get()
            assert msg.SerializeToString() == packet.publish[0].SerializeToString()

    await cleanup()

@pytest.mark.asyncio
async def test_gossip_propagation():
    # Create libp2p hosts
    next_msg_id_func = message_id_generator(0)

    num_hosts = 2
    libp2p_hosts = await create_libp2p_hosts(num_hosts)

    # Create pubsub, gossipsub instances
    pubsubs, gossipsubs = create_pubsub_and_gossipsub_instances(libp2p_hosts, \
                                                                SUPPORTED_PROTOCOLS, \
                                                                1, 0, 2, 30, 50, 100, 0.5)
    node1, node2 = libp2p_hosts[0], libp2p_hosts[1]
    sub1, sub2 = pubsubs[0], pubsubs[1]
    gsub1, gsub2 = gossipsubs[0], gossipsubs[1]

    node1_queue = await sub1.subscribe('foo')

    # node 1 publish to topic
    msg_content = 'foo_msg'
    node1_id = str(node1.get_id())

    # Generate message packet
    packet = generate_RPC_packet(node1_id, ["foo"], msg_content, next_msg_id_func())

    # publish from the randomly chosen host
    await gsub1.publish(node1_id, packet.SerializeToString())

    # now node 2 subscribes
    node2_queue = await sub2.subscribe('foo')

    await connect(node2, node1)

    # wait for gossip heartbeat
    await asyncio.sleep(2)

    # should be able to read message
    msg = await node2_queue.get()
    assert msg.SerializeToString() == packet.publish[0].SerializeToString()

    await cleanup()
