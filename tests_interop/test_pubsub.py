import functools
import math

from p2pclient.pb import p2pd_pb2
import pytest
import trio

from libp2p.io.trio import TrioTCPStream
from libp2p.peer.id import ID
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.subscription import TrioSubscriptionAPI
from libp2p.tools.factories import PubsubFactory
from libp2p.tools.interop.utils import connect
from libp2p.utils import read_varint_prefixed_bytes

TOPIC_0 = "ABALA"
TOPIC_1 = "YOOOO"


async def p2pd_subscribe(p2pd, topic, nursery):
    stream = TrioTCPStream(await p2pd.control.pubsub_subscribe(topic))
    send_channel, receive_channel = trio.open_memory_channel(math.inf)

    sub = TrioSubscriptionAPI(receive_channel, unsubscribe_fn=stream.close)

    async def _read_pubsub_msg() -> None:
        while True:
            msg_bytes = await read_varint_prefixed_bytes(stream)
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
            await send_channel.send(msg)

    nursery.start_soon(_read_pubsub_msg)
    return sub


def validate_pubsub_msg(msg: rpc_pb2.Message, data: bytes, from_peer_id: ID) -> None:
    assert msg.data == data and msg.from_id == from_peer_id


@pytest.mark.parametrize(
    "is_pubsub_signing, is_pubsub_signing_strict", ((True, True), (False, False))
)
@pytest.mark.parametrize("is_gossipsub", (True, False))
@pytest.mark.parametrize("num_p2pds", (2,))
@pytest.mark.trio
async def test_pubsub(
    p2pds, is_gossipsub, security_protocol, is_pubsub_signing_strict, nursery
):
    pubsub_factory = None
    if is_gossipsub:
        pubsub_factory = PubsubFactory.create_batch_with_gossipsub
    else:
        pubsub_factory = PubsubFactory.create_batch_with_floodsub

    async with pubsub_factory(
        1, security_protocol=security_protocol, strict_signing=is_pubsub_signing_strict
    ) as pubsubs:
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
        sub_go_0_topic_0 = await p2pd_subscribe(p2pds[0], TOPIC_0, nursery)
        sub_go_0_topic_1 = await p2pd_subscribe(p2pds[0], TOPIC_1, nursery)
        sub_go_1_topic_1 = await p2pd_subscribe(p2pds[1], TOPIC_1, nursery)
        # Check topic peers
        await trio.sleep(0.1)
        # go_0
        go_0_topic_0_peers = await p2pds[0].control.pubsub_list_peers(TOPIC_0)
        assert len(go_0_topic_0_peers) == 1 and py_peer_id == go_0_topic_0_peers[0]
        go_0_topic_1_peers = await p2pds[0].control.pubsub_list_peers(TOPIC_1)
        assert len(go_0_topic_1_peers) == 1 and py_peer_id == go_0_topic_1_peers[0]
        # py
        py_topic_0_peers = list(py_pubsub.peer_topics[TOPIC_0])
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
        await trio.sleep(0.1)
        assert py_peer_id not in (await p2pds[0].control.pubsub_list_peers(TOPIC_0))
        assert py_peer_id not in (await p2pds[1].control.pubsub_list_peers(TOPIC_0))
        await py_pubsub.subscribe(TOPIC_0)
        await trio.sleep(0.1)
        assert py_peer_id in (await p2pds[0].control.pubsub_list_peers(TOPIC_0))
        assert py_peer_id in (await p2pds[1].control.pubsub_list_peers(TOPIC_0))
