import asyncio
import pytest
import random

from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.pubsub import Pubsub
from utils import message_id_generator, generate_RPC_packet, \
    create_libp2p_hosts, create_pubsub_and_gossipsub_instances, sparse_connect, dense_connect
from tests.utils import cleanup

SUPPORTED_PROTOCOLS = ["/gossipsub/1.0.0"]


@pytest.mark.asyncio
async def test_sparse():
    # Create libp2p hosts
    print("Enter test")
    next_msg_id_func = message_id_generator(0)

    print("creating hosts")
    num_hosts = 10
    num_msgs = 5
    libp2p_hosts = await create_libp2p_hosts(num_hosts)

    print("creating pubsub")
    # Create pubsub, gossipsub instances
    pubsubs, gossipsubs = create_pubsub_and_gossipsub_instances(libp2p_hosts, \
                                                                SUPPORTED_PROTOCOLS, \
                                                                10, 9, 11, 30, 3, 5, 0.5)

    # All pubsub subscribe to foobar
    print("subscribing nodes")
    queues = []
    for pubsub in pubsubs:
        q = await pubsub.subscribe("foobar")

        # Add each blocking queue to an array of blocking queues
        queues.append(q)

    print("connecting")
    # Sparsely connect libp2p hosts in random way
    await dense_connect(libp2p_hosts)

    print("ZZZZZZs")
    # Wait 2 seconds for heartbeat to allow mesh to connect
    await asyncio.sleep(2)

    print("sending messages")
    for i in range(num_msgs):
        print("Message sending")
        msg_content = "foo " + str(i)

        # randomly pick a message origin
        origin_idx = random.randint(0, num_hosts - 1)
        origin_host = libp2p_hosts[origin_idx]
        host_id = str(origin_host.get_id())

        # Generate message packet
        packet = generate_RPC_packet(host_id, ["foobar"], msg_content, next_msg_id_func())

        # publish from the randomly chosen host
        await gossipsubs[origin_idx].publish(host_id, packet.SerializeToString())

        await asyncio.sleep(1)
        # Assert that all blocking queues receive the message
        for queue in queues:
            print("pre-get")
            msg = await queue.get()
            print(msg)
            print("post-get")
            assert msg.SerializeToString() == packet.publish[0].SerializeToString()
        print("Message acked")
    await cleanup()
