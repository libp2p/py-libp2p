import struct
from typing import Sequence

from libp2p.peer.id import ID
from libp2p.pubsub.pb import rpc_pb2
from libp2p.tools.utils import connect


def message_id_generator(start_val):
    """
    Generate a unique message id.

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
        return struct.pack(">Q", val)

    return generator


def make_pubsub_msg(
    origin_id: ID, topic_ids: Sequence[str], data: bytes, seqno: bytes
) -> rpc_pb2.Message:
    return rpc_pb2.Message(
        from_id=origin_id.to_bytes(), seqno=seqno, data=data, topicIDs=list(topic_ids)
    )


# FIXME: There is no difference between `sparse_connect` and `dense_connect`,
#   before `connect_some` is fixed.


async def sparse_connect(hosts):
    await connect_some(hosts, 3)


async def dense_connect(hosts):
    await connect_some(hosts, 10)


async def connect_all(hosts):
    for i, host in enumerate(hosts):
        for host2 in hosts[i + 1 :]:
            await connect(host, host2)


# FIXME: `degree` is not used at all
async def connect_some(hosts, degree):
    for i, host in enumerate(hosts):
        for host2 in hosts[i + 1 :]:
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
