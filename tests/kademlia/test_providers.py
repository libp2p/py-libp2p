import pytest

from libp2p.kademlia.network import KademliaServer


@pytest.mark.asyncio
async def test_example():
    node_a = KademliaServer()
    await node_a.listen(5801)

    node_b = KademliaServer()
    await node_b.listen(5802)
    await node_b.bootstrap([("127.0.0.1", 5801)])

    key = "hello"
    value = "world"
    await node_b.set(key, value)
    await node_b.provide("hello")

    providers = await node_b.get_providers("hello")

    # bmuller's handle_call_response wraps
    # every rpc call result in a list of tuples
    # [(True, [b'\xf9\xa1\xf5\x10a\xe5\xe0F'])]
    first_tuple = providers[0]
    # (True, [b'\xf9\xa1\xf5\x10a\xe5\xe0F'])
    first_providers = first_tuple[1]
    # [b'\xf9\xa1\xf5\x10a\xe5\xe0F']
    first_provider = first_providers[0]
    assert node_b.node.peer_id_bytes == first_provider
