import pytest
import trio

from libp2p.tools.factories import HostFactory
from libp2p.tools.interop.utils import connect


@pytest.mark.trio
async def test_connect(is_host_secure, p2pds):
    async with HostFactory.create_batch_and_listen(is_host_secure, 1) as hosts:
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
        await trio.sleep(0.01)
        assert len(host.get_network().connections) == 0
