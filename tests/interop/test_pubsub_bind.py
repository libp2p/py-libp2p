import pytest

from .daemon import make_p2pd


@pytest.mark.parametrize("num_hosts", (1,))
@pytest.mark.asyncio
async def test_pubsub_init(
    hosts, proc_factory, is_host_secure, unused_tcp_port_factory
):
    p2pd = await make_p2pd(proc_factory, unused_tcp_port_factory, is_host_secure)
