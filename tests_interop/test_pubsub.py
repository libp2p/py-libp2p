import asyncio
import functools

from p2pclient.pb import p2pd_pb2
import pytest

from libp2p.peer.id import ID
from libp2p.pubsub.pb import rpc_pb2
from libp2p.utils import read_varint_prefixed_bytes

from .utils import connect

TOPIC_0 = "ABALA"
TOPIC_1 = "YOOOO"


async def p2pd_subscribe(p2pd, topic) -> "asyncio.Queue[rpc_pb2.Message]":
    reader, writer = await p2pd.control.pubsub_subscribe(topic)

    queue = asyncio.Queue()

    async def _read_pubsub_msg() -> None:
        writer_closed_task = asyncio.ensure_future(writer.wait_closed())

        while True:
            done, pending = await asyncio.wait(
                [read_varint_prefixed_bytes(reader), writer_closed_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            done_tasks = tuple(done)
            if writer.is_closing():
                return
            read_task = done_tasks[0]
            # Sanity check
            assert read_task._coro.__name__ == "read_varint_prefixed_bytes"
            msg_bytes = read_task.result()
            ps_msg = p2pd_pb2.PSMessage()
            ps_msg.ParseFromString(msg_bytes)
            # Fill in the message used in py-libp2p
            msg = rpc_pb2.Message(
                from_id=ps_msg.from_id,
                data=ps_msg.data,
                seqno=ps_msg.seqno,
                topicIDs=ps_msg.topicIDs,
                signature=ps_msg.signature,
                key=ps_msg.key,
            )
            queue.put_nowait(msg)

    asyncio.ensure_future(_read_pubsub_msg())
    await asyncio.sleep(0)
    return queue


def validate_pubsub_msg(msg: rpc_pb2.Message, data: bytes, from_peer_id: ID) -> None:
    assert msg.data == data and msg.from_id == from_peer_id


@pytest.mark.parametrize("is_gossipsub", (True, False))
@pytest.mark.parametrize("num_hosts, num_p2pds", ((1, 2),))
@pytest.mark.asyncio
async def test_pubsub(pubsubs, p2pds):
    #
    # Test: Recognize pubsub peers on connection.
    #
    py_pubsub = pubsubs[0]
    # go0 <-> py <-> go1
    await connect(p2pds[0], py_pubsub.host)
    await connect(py_pubsub.host, p2pds[1])
    py_peer_id = py_pubsub.host.get_id()
    # Check pubsub peers
    pubsub_peers_0 = await p2pds[0].control.pubsub_list_peers("")
    assert len(pubsub_peers_0) == 1 and pubsub_peers_0[0] == py_peer_id
    pubsub_peers_1 = await p2pds[1].control.pubsub_list_peers("")
    assert len(pubsub_peers_1) == 1 and pubsub_peers_1[0] == py_peer_id
    assert (
        len(py_pubsub.peers) == 2
        and p2pds[0].peer_id in py_pubsub.peers
        and p2pds[1].peer_id in py_pubsub.peers
    )

    #
    # Test: `subscribe`.
    #
    # (name, topics)
    # (go_0, [0, 1]) <-> (py, [0, 1]) <-> (go_1, [1])
    sub_py_topic_0 = await py_pubsub.subscribe(TOPIC_0)
    sub_py_topic_1 = await py_pubsub.subscribe(TOPIC_1)
    sub_go_0_topic_0 = await p2pd_subscribe(p2pds[0], TOPIC_0)
    sub_go_0_topic_1 = await p2pd_subscribe(p2pds[0], TOPIC_1)
    sub_go_1_topic_1 = await p2pd_subscribe(p2pds[1], TOPIC_1)
    # Check topic peers
    await asyncio.sleep(0.1)
    # go_0
    go_0_topic_0_peers = await p2pds[0].control.pubsub_list_peers(TOPIC_0)
    assert len(go_0_topic_0_peers) == 1 and py_peer_id == go_0_topic_0_peers[0]
    go_0_topic_1_peers = await p2pds[0].control.pubsub_list_peers(TOPIC_1)
    assert len(go_0_topic_1_peers) == 1 and py_peer_id == go_0_topic_1_peers[0]
    # py
    py_topic_0_peers = py_pubsub.peer_topics[TOPIC_0]
    assert len(py_topic_0_peers) == 1 and p2pds[0].peer_id == py_topic_0_peers[0]
    # go_1
    go_1_topic_1_peers = await p2pds[1].control.pubsub_list_peers(TOPIC_1)
    assert len(go_1_topic_1_peers) == 1 and py_peer_id == go_1_topic_1_peers[0]

    #
    # Test: `publish`
    #
    #  1. py publishes
    #    - 1.1. py publishes data_11 to topic_0, py and go_0 receives.
    #    - 1.2. py publishes data_12 to topic_1, all receive.
    #  2. go publishes
    #    - 2.1. go_0 publishes data_21 to topic_0, py and go_0 receive.
    #    - 2.2. go_1 publishes data_22 to topic_1, all receive.

    # 1.1. py publishes data_11 to topic_0, py and go_0 receives.
    data_11 = b"data_11"
    await py_pubsub.publish(TOPIC_0, data_11)
    validate_11 = functools.partial(
        validate_pubsub_msg, data=data_11, from_peer_id=py_peer_id
    )
    validate_11(await sub_py_topic_0.get())
    validate_11(await sub_go_0_topic_0.get())

    # 1.2. py publishes data_12 to topic_1, all receive.
    data_12 = b"data_12"
    validate_12 = functools.partial(
        validate_pubsub_msg, data=data_12, from_peer_id=py_peer_id
    )
    await py_pubsub.publish(TOPIC_1, data_12)
    validate_12(await sub_py_topic_1.get())
    validate_12(await sub_go_0_topic_1.get())
    validate_12(await sub_go_1_topic_1.get())

    # 2.1. go_0 publishes data_21 to topic_0, py and go_0 receive.
    data_21 = b"data_21"
    validate_21 = functools.partial(
        validate_pubsub_msg, data=data_21, from_peer_id=p2pds[0].peer_id
    )
    await p2pds[0].control.pubsub_publish(TOPIC_0, data_21)
    validate_21(await sub_py_topic_0.get())
    validate_21(await sub_go_0_topic_0.get())

    # 2.2. go_1 publishes data_22 to topic_1, all receive.
    data_22 = b"data_22"
    validate_22 = functools.partial(
        validate_pubsub_msg, data=data_22, from_peer_id=p2pds[1].peer_id
    )
    await p2pds[1].control.pubsub_publish(TOPIC_1, data_22)
    validate_22(await sub_py_topic_1.get())
    validate_22(await sub_go_0_topic_1.get())
    validate_22(await sub_go_1_topic_1.get())

    #
    # Test: `unsubscribe` and re`subscribe`
    #
    await py_pubsub.unsubscribe(TOPIC_0)
    await asyncio.sleep(0.1)
    assert py_peer_id not in (await p2pds[0].control.pubsub_list_peers(TOPIC_0))
    assert py_peer_id not in (await p2pds[1].control.pubsub_list_peers(TOPIC_0))
    await py_pubsub.subscribe(TOPIC_0)
    await asyncio.sleep(0.1)
    assert py_peer_id in (await p2pds[0].control.pubsub_list_peers(TOPIC_0))
    assert py_peer_id in (await p2pds[1].control.pubsub_list_peers(TOPIC_0))
