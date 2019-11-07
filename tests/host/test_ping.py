import asyncio
import secrets

import pytest

from libp2p.host.ping import ID, PING_LENGTH
from libp2p.peer.peerinfo import info_from_p2p_addr
from tests.utils import set_up_nodes_by_transport_opt


@pytest.mark.asyncio
async def test_ping_once():
    transport_opt_list = [["/ip4/127.0.0.1/tcp/0"], ["/ip4/127.0.0.1/tcp/0"]]
    (host_a, host_b) = await set_up_nodes_by_transport_opt(transport_opt_list)

    addr = host_a.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await host_b.connect(info)

    stream = await host_b.new_stream(host_a.get_id(), (ID,))
    some_ping = secrets.token_bytes(PING_LENGTH)
    await stream.write(some_ping)
    some_pong = await stream.read(PING_LENGTH)
    assert some_ping == some_pong
    await stream.close()


SOME_PING_COUNT = 3


@pytest.mark.asyncio
async def test_ping_several():
    transport_opt_list = [["/ip4/127.0.0.1/tcp/0"], ["/ip4/127.0.0.1/tcp/0"]]
    (host_a, host_b) = await set_up_nodes_by_transport_opt(transport_opt_list)

    addr = host_a.get_addrs()[0]
    info = info_from_p2p_addr(addr)
    await host_b.connect(info)

    stream = await host_b.new_stream(host_a.get_id(), (ID,))
    for _ in range(SOME_PING_COUNT):
        some_ping = secrets.token_bytes(PING_LENGTH)
        await stream.write(some_ping)
        some_pong = await stream.read(PING_LENGTH)
        assert some_ping == some_pong
        # NOTE: simulate some time to sleep to mirror a real
        # world usage where a peer sends pings on some periodic interval
        # NOTE: this interval can be `0` for this test.
        await asyncio.sleep(0)
    await stream.close()
