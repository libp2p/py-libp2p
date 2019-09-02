import asyncio

import pytest

from libp2p.peer.id import ID

from .utils import connect

TOPIC = "TOPIC_0123"
DATA = b"DATA_0123"


@pytest.mark.parametrize("num_hosts", (1,))
@pytest.mark.asyncio
async def test_pubsub_subscribe(pubsubs_gsub, p2pds):
    # await connect(pubsubs_gsub[0].host, p2pds[0])
    await connect(p2pds[0], pubsubs_gsub[0].host)
    peers = await p2pds[0].control.pubsub_list_peers("")
    assert pubsubs_gsub[0].host.get_id() in peers
    # FIXME:
    assert p2pds[0].peer_id in pubsubs_gsub[0].peers

    sub = await pubsubs_gsub[0].subscribe(TOPIC)
    peers_topic = await p2pds[0].control.pubsub_list_peers(TOPIC)
    await asyncio.sleep(0.1)
    assert pubsubs_gsub[0].host.get_id() in peers_topic

    await p2pds[0].control.pubsub_publish(TOPIC, DATA)
    msg = await sub.get()
    assert ID(msg.from_id) == p2pds[0].peer_id
    assert msg.data == DATA
    assert len(msg.topicIDs) == 1 and msg.topicIDs[0] == TOPIC
