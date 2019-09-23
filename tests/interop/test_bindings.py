import asyncio

import pytest

from .utils import connect


@pytest.mark.parametrize("num_hosts", (1,))
@pytest.mark.asyncio
async def test_connect(hosts, p2pds):
    p2pd = p2pds[0]
    host = hosts[0]
    assert len(await p2pd.control.list_peers()) == 0
    # Test: connect from Py
    await connect(host, p2pd)
    assert len(await p2pd.control.list_peers()) == 1
    # Test: `disconnect` from Py
    await host.disconnect(p2pd.peer_id)
    assert len(await p2pd.control.list_peers()) == 0
    # Test: connect from Go
    await connect(p2pd, host)
    assert len(host.get_network().connections) == 1
    # Test: `disconnect` from Go
    await p2pd.control.disconnect(host.get_id())
    await asyncio.sleep(0.01)
    assert len(host.get_network().connections) == 0
