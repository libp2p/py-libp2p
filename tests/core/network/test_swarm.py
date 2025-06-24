import pytest
from multiaddr import (
    Multiaddr,
)
import trio
from trio.testing import (
    wait_all_tasks_blocked,
)

from libp2p import (
    new_swarm,
)
from libp2p.network.exceptions import (
    SwarmException,
)
from libp2p.network.swarm import (
    Swarm,
)
from libp2p.tools.utils import (
    connect_swarm,
)
from libp2p.transport.tcp.tcp import (
    TCP,
)
from tests.utils.factories import (
    SwarmFactory,
)


@pytest.mark.trio
async def test_swarm_dial_peer(security_protocol):
    async with SwarmFactory.create_batch_and_listen(
        3, security_protocol=security_protocol
    ) as swarms:
        # Test: No addr found.
        with pytest.raises(SwarmException):
            await swarms[0].dial_peer(swarms[1].get_peer_id())

        # Test: len(addr) in the peerstore is 0.
        swarms[0].peerstore.add_addrs(swarms[1].get_peer_id(), [], 10000)
        with pytest.raises(SwarmException):
            await swarms[0].dial_peer(swarms[1].get_peer_id())

        # Test: Succeed if addrs of the peer_id are present in the peerstore.
        addrs = tuple(
            addr
            for transport in swarms[1].listeners.values()
            for addr in transport.get_addrs()
        )
        swarms[0].peerstore.add_addrs(swarms[1].get_peer_id(), addrs, 10000)
        await swarms[0].dial_peer(swarms[1].get_peer_id())
        assert swarms[0].get_peer_id() in swarms[1].connections
        assert swarms[1].get_peer_id() in swarms[0].connections

        # Test: Reuse connections when we already have ones with a peer.
        conn_to_1 = swarms[0].connections[swarms[1].get_peer_id()]
        conn = await swarms[0].dial_peer(swarms[1].get_peer_id())
        assert conn is conn_to_1


@pytest.mark.trio
async def test_swarm_close_peer(security_protocol):
    async with SwarmFactory.create_batch_and_listen(
        3, security_protocol=security_protocol
    ) as swarms:
        # 0 <> 1 <> 2
        await connect_swarm(swarms[0], swarms[1])
        await connect_swarm(swarms[1], swarms[2])

        # peer 1 closes peer 0
        await swarms[1].close_peer(swarms[0].get_peer_id())
        await trio.sleep(0.01)
        await wait_all_tasks_blocked()
        # 0  1 <> 2
        assert len(swarms[0].connections) == 0
        assert (
            len(swarms[1].connections) == 1
            and swarms[2].get_peer_id() in swarms[1].connections
        )

        # peer 1 is closed by peer 2
        await swarms[2].close_peer(swarms[1].get_peer_id())
        await trio.sleep(0.01)
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
        await trio.sleep(0.01)
        # 0  1  2
        assert len(swarms[1].connections) == 0 and len(swarms[2].connections) == 0


@pytest.mark.trio
async def test_swarm_remove_conn(swarm_pair):
    swarm_0, swarm_1 = swarm_pair
    conn_0 = swarm_0.connections[swarm_1.get_peer_id()]
    swarm_0.remove_conn(conn_0)
    assert swarm_1.get_peer_id() not in swarm_0.connections
    # Test: Remove twice. There should not be errors.
    swarm_0.remove_conn(conn_0)
    assert swarm_1.get_peer_id() not in swarm_0.connections


@pytest.mark.trio
async def test_swarm_multiaddr(security_protocol):
    async with SwarmFactory.create_batch_and_listen(
        3, security_protocol=security_protocol
    ) as swarms:

        def clear():
            swarms[0].peerstore.clear_addrs(swarms[1].get_peer_id())

        clear()
        # No addresses
        with pytest.raises(SwarmException):
            await swarms[0].dial_peer(swarms[1].get_peer_id())

        clear()
        # Wrong addresses
        swarms[0].peerstore.add_addrs(
            swarms[1].get_peer_id(), [Multiaddr("/ip4/0.0.0.0/tcp/9999")], 10000
        )

        with pytest.raises(SwarmException):
            await swarms[0].dial_peer(swarms[1].get_peer_id())

        clear()
        # Multiple wrong addresses
        swarms[0].peerstore.add_addrs(
            swarms[1].get_peer_id(),
            [Multiaddr("/ip4/0.0.0.0/tcp/9999"), Multiaddr("/ip4/0.0.0.0/tcp/9998")],
            10000,
        )

        with pytest.raises(SwarmException):
            await swarms[0].dial_peer(swarms[1].get_peer_id())

        # Test one address
        addrs = tuple(
            addr
            for transport in swarms[1].listeners.values()
            for addr in transport.get_addrs()
        )

        swarms[0].peerstore.add_addrs(swarms[1].get_peer_id(), addrs[:1], 10000)
        await swarms[0].dial_peer(swarms[1].get_peer_id())

        # Test multiple addresses
        addrs = tuple(
            addr
            for transport in swarms[1].listeners.values()
            for addr in transport.get_addrs()
        )

        swarms[0].peerstore.add_addrs(swarms[1].get_peer_id(), addrs + addrs, 10000)
        await swarms[0].dial_peer(swarms[1].get_peer_id())


def test_new_swarm_defaults_to_tcp():
    swarm = new_swarm()
    assert isinstance(swarm, Swarm)
    assert isinstance(swarm.transport, TCP)


def test_new_swarm_tcp_multiaddr_supported():
    addr = Multiaddr("/ip4/127.0.0.1/tcp/9999")
    swarm = new_swarm(listen_addrs=[addr])
    assert isinstance(swarm, Swarm)
    assert isinstance(swarm.transport, TCP)


def test_new_swarm_quic_multiaddr_raises():
    addr = Multiaddr("/ip4/127.0.0.1/udp/9999/quic")
    with pytest.raises(ValueError, match="QUIC not yet supported"):
        new_swarm(listen_addrs=[addr])
