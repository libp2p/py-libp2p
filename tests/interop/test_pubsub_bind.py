import pytest

from .daemon import make_p2pd


@pytest.mark.parametrize("num_hosts", (1,))
@pytest.mark.asyncio
async def test_pubsub_init(hosts, is_host_secure, unused_tcp_port_factory):
    try:
        p2pd = await make_p2pd(unused_tcp_port_factory, is_host_secure)
        host = hosts[0]
        peers = await p2pd.control.list_peers()
        assert len(peers) == 0
        await host.connect(p2pd.peer_info)
        peers = await p2pd.control.list_peers()
        assert len(peers) != 0
    finally:
        await p2pd.close()
