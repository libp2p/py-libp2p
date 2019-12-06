import asyncio

import pytest

from libp2p.host.exceptions import ConnectionFailure
from libp2p.peer.peerinfo import PeerInfo
from libp2p.tools.utils import set_up_nodes_by_transport_opt, set_up_routed_hosts


@pytest.mark.asyncio
async def test_host_routing_success():
    host_a, host_b = await set_up_routed_hosts()
    # forces to use routing as no addrs are provided
    await host_a.connect(PeerInfo(host_b.get_id(), []))
    await host_b.connect(PeerInfo(host_a.get_id(), []))

    # Clean up
    await asyncio.gather(*[host_a.close(), host_b.close()])


@pytest.mark.asyncio
async def test_host_routing_fail():
    host_a, host_b = await set_up_routed_hosts()
    basic_host_c = (await set_up_nodes_by_transport_opt([["/ip4/127.0.0.1/tcp/0"]]))[0]

    # routing fails because host_c does not use routing
    with pytest.raises(ConnectionFailure):
        await host_a.connect(PeerInfo(basic_host_c.get_id(), []))
    with pytest.raises(ConnectionFailure):
        await host_b.connect(PeerInfo(basic_host_c.get_id(), []))

    # Clean up
    await asyncio.gather(*[host_a.close(), host_b.close(), basic_host_c.close()])
