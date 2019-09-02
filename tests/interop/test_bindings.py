import asyncio

from multiaddr import Multiaddr
import pytest


@pytest.mark.parametrize("num_hosts", (1,))
@pytest.mark.asyncio
async def test_connect(hosts, p2pds):
    p2pd = p2pds[0]
    host = hosts[0]
    assert len(await p2pd.control.list_peers()) == 0
    # Test: connect from Py
    await host.connect(p2pd.peer_info)
    assert len(await p2pd.control.list_peers()) == 1
    # Test: `disconnect` from Py
    await host.disconnect(p2pd.peer_id)
    assert len(await p2pd.control.list_peers()) == 0
    # Test: connect from Go
    py_peer_id = host.get_id()
    await p2pd.control.connect(
        host.get_id(),
        [host.get_addrs()[0].decapsulate(Multiaddr(f"/p2p/{py_peer_id.to_string()}"))],
    )
    assert len(host.get_network().connections) == 1
    # Test: `disconnect` from Go
    await p2pd.control.disconnect(py_peer_id)
    # FIXME: Failed to handle disconnect
    # assert len(host.get_network().connections) == 0
