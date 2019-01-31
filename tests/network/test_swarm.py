import pytest

from multiaddr import Multiaddr

from libp2p import new_node
from libp2p.network.swarm import SwarmException

@pytest.mark.asyncio
async def test_dial_unknown_peer():
    node = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    swarm = node.get_network()
    swarm.peerstore.put(1, "this is only for test purpose", 1)
    with pytest.raises(SwarmException):
        await swarm.dial_peer(1)

@pytest.mark.asyncio
async def test_stream_unknown_peer():
    node = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])
    swarm = node.get_network()
    swarm.peerstore.put(1, "this is only for test purpose", 1)
    with pytest.raises(SwarmException):
        await swarm.new_stream(1, "nullPacket/1.0.0")

@pytest.mark.asyncio
async def test_listen_an_already_listened_addr():
    addr_str = "/ip4/127.0.0.1/tcp/8000"
    node = await new_node(transport_opt=[addr_str])
    await node.get_network().listen(Multiaddr(addr_str))

@pytest.mark.asyncio
async def test_listen_addr_wont_listen():
    node = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/8000"])
    # Trying to listen on 1.1.1.1 should fail because 1.1.1.1 isn't our IP
    assert not await node.get_network().listen(Multiaddr("/ip4/1.1.1.1/tcp/8000"))
