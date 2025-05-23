import pytest
import trio

from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from tests.utils.factories import (
    HostFactory,
)


async def connect_two(host_a, host_b, host_c):
    # Initially all of the hosts are disconnected
    assert (len(host_a.get_connected_peers())) == 0
    assert (len(host_b.get_connected_peers())) == 0
    assert (len(host_c.get_connected_peers())) == 0

    # Connecting hostA with hostB
    addr = host_b.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await host_a.connect(info)

    # Since hostA and hostB are connected now
    assert (len(host_a.get_connected_peers())) == 1
    assert (len(host_b.get_connected_peers())) == 1
    assert (len(host_c.get_connected_peers())) == 0
    assert host_a.get_connected_peers()[0] == host_b.get_id()
    assert host_b.get_connected_peers()[0] == host_a.get_id()


async def connect_three_cyclic(host_a, host_b, host_c):
    # Connecting hostA with hostB
    addr = host_b.get_addrs()[0]
    infoB = info_from_p2p_addr(addr)
    await host_a.connect(infoB)

    # Connecting hostB with hostC
    addr = host_c.get_addrs()[0]
    infoC = info_from_p2p_addr(addr)
    await host_b.connect(infoC)

    # Connecting hostC with hostA
    addr = host_a.get_addrs()[0]
    infoA = info_from_p2p_addr(addr)
    await host_c.connect(infoA)

    # Performing checks
    assert (len(host_a.get_connected_peers())) == 2
    assert (len(host_b.get_connected_peers())) == 2
    assert (len(host_c.get_connected_peers())) == 2
    assert host_a.get_connected_peers() == [host_b.get_id(), host_c.get_id()]
    assert host_b.get_connected_peers() == [host_a.get_id(), host_c.get_id()]
    assert host_c.get_connected_peers() == [host_b.get_id(), host_a.get_id()]


async def connect_two_to_one(host_a, host_b, host_c):
    # Connecting hostA and hostC to hostB
    addr = host_b.get_addrs()[0]
    infoB = info_from_p2p_addr(addr)
    await host_a.connect(infoB)
    await host_c.connect(infoB)

    # Performing checks
    assert (len(host_a.get_connected_peers())) == 1
    assert (len(host_b.get_connected_peers())) == 2
    assert (len(host_c.get_connected_peers())) == 1
    assert host_a.get_connected_peers() == [host_b.get_id()]
    assert host_b.get_connected_peers() == [host_a.get_id(), host_c.get_id()]
    assert host_c.get_connected_peers() == [host_b.get_id()]


async def connect_and_disconnect(host_a, host_b, host_c):
    # Connecting hostB to hostA and hostC
    addr = host_a.get_addrs()[0]
    infoA = info_from_p2p_addr(addr)
    await host_b.connect(infoA)
    addr = host_c.get_addrs()[0]
    infoC = info_from_p2p_addr(addr)
    await host_b.connect(infoC)

    # Performing checks
    assert (len(host_a.get_connected_peers())) == 1
    assert (len(host_b.get_connected_peers())) == 2
    assert (len(host_c.get_connected_peers())) == 1
    assert host_a.get_connected_peers() == [host_b.get_id()]
    assert host_b.get_connected_peers() == [host_a.get_id(), host_c.get_id()]
    assert host_c.get_connected_peers() == [host_b.get_id()]

    # Disconnecting hostB and hostA
    await host_b.disconnect(host_a.get_id())
    await trio.sleep(0.5)

    # Performing checks
    assert (len(host_a.get_connected_peers())) == 0
    assert (len(host_b.get_connected_peers())) == 1
    assert (len(host_c.get_connected_peers())) == 1
    assert host_b.get_connected_peers() == [host_c.get_id()]
    assert host_c.get_connected_peers() == [host_b.get_id()]


@pytest.mark.parametrize(
    "test",
    [
        (connect_two),
        (connect_three_cyclic),
        (connect_two_to_one),
        (connect_and_disconnect),
    ],
)
@pytest.mark.trio
async def test_connected_peers(test, security_protocol):
    async with HostFactory.create_batch_and_listen(
        3, security_protocol=security_protocol
    ) as hosts:
        await test(hosts[0], hosts[1], hosts[2])
