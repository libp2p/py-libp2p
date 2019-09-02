import asyncio

import pytest

from .utils import connect


TOPIC = "TOPIC_0123"


@pytest.mark.parametrize("num_hosts", (1,))
@pytest.mark.asyncio
async def test_pubsub_peers(pubsubs_gsub, p2pds):
    # await connect(pubsubs_gsub[0].host, p2pds[0])
    await connect(p2pds[0], pubsubs_gsub[0].host)
    sub = await pubsubs_gsub[0].subscribe(TOPIC)
    await asyncio.sleep(1)
    peers = await p2pds[0].control.pubsub_list_peers(TOPIC)
    print(f"!@# peers={peers}")
