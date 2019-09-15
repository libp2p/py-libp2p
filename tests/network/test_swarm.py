import asyncio

import pytest

from tests.factories import ListeningSwarmFactory
from tests.utils import connect_swarm


@pytest.mark.asyncio
async def test_swarm_close_peer(is_host_secure):
    swarms = await ListeningSwarmFactory.create_batch_and_listen(is_host_secure, 3)
    # 0 <> 1 <> 2
    await connect_swarm(swarms[0], swarms[1])
    await connect_swarm(swarms[1], swarms[2])

    # peer 1 closes peer 0
    await swarms[1].close_peer(swarms[0].get_peer_id())
    await asyncio.sleep(0.01)
    # 0  1 <> 2
    assert len(swarms[0].connections) == 0
    assert (
        len(swarms[1].connections) == 1
        and swarms[2].get_peer_id() in swarms[1].connections
    )

    # peer 1 is closed by peer 2
    await swarms[2].close_peer(swarms[1].get_peer_id())
    await asyncio.sleep(0.01)
    # 0  1  2
    assert len(swarms[1].connections) == 0 and len(swarms[2].connections) == 0

    await connect_swarm(swarms[0], swarms[1])
    # 0 <> 1  2
    assert (
        len(swarms[0].connections) == 1
        and swarms[1].get_peer_id() in swarms[0].connections
    )
    assert (
        len(swarms[1].connections) == 1
        and swarms[0].get_peer_id() in swarms[1].connections
    )
    # peer 0 closes peer 1
    await swarms[0].close_peer(swarms[1].get_peer_id())
    await asyncio.sleep(0.01)
    # 0  1  2
    assert len(swarms[1].connections) == 0 and len(swarms[2].connections) == 0

    # Clean up
    await asyncio.gather(*[swarm.close() for swarm in swarms])
