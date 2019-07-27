import asyncio
import random
import struct
from typing import (
    Sequence,
)
import uuid

import multiaddr

from libp2p import new_node
from libp2p.pubsub.pb import rpc_pb2
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.peer.id import ID
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.gossipsub import GossipSub

from tests.utils import connect


def message_id_generator(start_val):
    """
    Generate a unique message id
    :param start_val: value to start generating messages at
    :return: message id
    """
    val = start_val

    def generator():
        # Allow manipulation of val within closure
        nonlocal val

        # Increment id
        val += 1

        # Convert val to big endian
        return struct.pack('>Q', val)

    return generator


def make_pubsub_msg(
        origin_id: ID,
        topic_ids: Sequence[str],
        data: bytes,
        seqno: bytes) -> rpc_pb2.Message:
    return rpc_pb2.Message(
        from_id=origin_id.to_bytes(),
        seqno=seqno,
        data=data,
        topicIDs=list(topic_ids),
    )


def generate_RPC_packet(origin_id, topics, msg_content, msg_id):
    """
    Generate RPC packet to send over wire
    :param origin_id: peer id of the message origin
    :param topics: list of topics
    :param msg_content: string of content in data
    :param msg_id: seqno for the message
    """
    packet = rpc_pb2.RPC()
    message = rpc_pb2.Message(
        from_id=origin_id.encode('utf-8'),
        seqno=msg_id,
        data=msg_content.encode('utf-8'),
    )

    for topic in topics:
        message.topicIDs.extend([topic.encode('utf-8')])

    packet.publish.extend([message])
    return packet


async def create_libp2p_hosts(num_hosts):
    """
    Create libp2p hosts
    :param num_hosts: number of hosts to create
    """
    hosts = []
    tasks_create = []
    for i in range(0, num_hosts):
        # Create node
        tasks_create.append(asyncio.ensure_future(new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])))
    hosts = await asyncio.gather(*tasks_create)

    tasks_listen = []
    for node in hosts:
        # Start listener
        tasks_listen.append(asyncio.ensure_future(node.get_network().listen(multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0"))))
    await asyncio.gather(*tasks_listen)

    return hosts


def create_pubsub_and_gossipsub_instances(
        libp2p_hosts,
        supported_protocols,
        degree,
        degree_low,
        degree_high,
        time_to_live,
        gossip_window,
        gossip_history,
        heartbeat_interval):
    pubsubs = []
    gossipsubs = []
    for node in libp2p_hosts:
        gossipsub = GossipSub(supported_protocols, degree,
                              degree_low, degree_high, time_to_live,
                              gossip_window, gossip_history,
                              heartbeat_interval)
        pubsub = Pubsub(node, gossipsub, "a")
        pubsubs.append(pubsub)
        gossipsubs.append(gossipsub)

    return pubsubs, gossipsubs


# FIXME: There is no difference between `sparse_connect` and `dense_connect`,
#   before `connect_some` is fixed.

async def sparse_connect(hosts):
    await connect_some(hosts, 3)


async def dense_connect(hosts):
    await connect_some(hosts, 10)


# FIXME: `degree` is not used at all
async def connect_some(hosts, degree):
    for i, host in enumerate(hosts):
        for j, host2 in enumerate(hosts):
            if i != j and i < j:
                await connect(host, host2)

    # TODO: USE THE CODE BELOW
    # for i, host in enumerate(hosts):
    #     j = 0
    #     while j < degree:
    #         n = random.randint(0, len(hosts) - 1)

    #         if n == i:
    #             j -= 1
    #             continue

    #         neighbor = hosts[n]

    #         await connect(host, neighbor)

    #         j += 1


async def one_to_all_connect(hosts, central_host_index):
    for i, host in enumerate(hosts):
        if i != central_host_index:
            await connect(hosts[central_host_index], host)
