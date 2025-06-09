import pytest

from libp2p.host.exceptions import (
    ConnectionFailure,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from tests.utils.factories import (
    HostFactory,
    RoutedHostFactory,
)


@pytest.mark.trio
async def test_host_routing_success():
    async with RoutedHostFactory.create_batch_and_listen(2) as hosts:
        # forces to use routing as no addrs are provided
        await hosts[0].connect(PeerInfo(hosts[1].get_id(), []))
        await hosts[1].connect(PeerInfo(hosts[0].get_id(), []))


@pytest.mark.trio
async def test_host_routing_fail():
    async with (
        RoutedHostFactory.create_batch_and_listen(2) as routed_hosts,
        HostFactory.create_batch_and_listen(1) as basic_hosts,
    ):
        # routing fails because host_c does not use routing
        with pytest.raises(ConnectionFailure):
            await routed_hosts[0].connect(PeerInfo(basic_hosts[0].get_id(), []))
        with pytest.raises(ConnectionFailure):
            await routed_hosts[1].connect(PeerInfo(basic_hosts[0].get_id(), []))
