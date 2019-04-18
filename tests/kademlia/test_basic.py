import pytest
from libp2p.kademlia.network import Server
import math


@pytest.mark.asyncio
async def test_example():
    node_a = Server()
    await node_a.listen(5678)

    node_b = Server()
    await node_b.listen(5679)

    # Bootstrap the node by connecting to other known nodes, in this case
    # replace 123.123.123.123 with the IP of another node and optionally
    # give as many ip/port combos as you can for other nodes.
    await node_b.bootstrap([("127.0.0.1", 5678)])

    # set a value for the key "my-key" on the network
    value = "my-value"
    key = "my-key"
    await node_b.set(key, value)

    # get the value associated with "my-key" from the network
    assert await node_b.get(key) == value
    assert await node_a.get(key) == value


@pytest.mark.parametrize("nodes_nr", [(2**i) for i in range(2, 5)])
@pytest.mark.asyncio
async def test_multiple_nodes_bootstrap_set_get(nodes_nr):

    node_bootstrap = Server()
    await node_bootstrap.listen(3000 + nodes_nr * 2)

    nodes = []
    for i in range(nodes_nr):
        node = Server()
        addrs = [("127.0.0.1", 3000 + nodes_nr * 2)]
        await node.listen(3001 + i + nodes_nr * 2)
        await node.bootstrap(addrs)
        nodes.append(node)

    for i, node in enumerate(nodes):
        # set a value for the key "my-key" on the network
        value = "my awesome value %d" % i
        key = "set from %d" % i
        await node.set(key, value)

    for i in range(nodes_nr):
        for node in nodes:
            value = "my awesome value %d" % i
            key = "set from %d" % i
            assert await node.get(key) == value


@pytest.mark.parametrize("nodes_nr", [(2**i) for i in range(2, 5)])
@pytest.mark.asyncio
async def test_multiple_nodes_set_bootstrap_get(nodes_nr):
    node_bootstrap = Server()
    await node_bootstrap.listen(2000 + nodes_nr * 2)
    
    nodes = []
    for i in range(nodes_nr):
        node = Server()
        addrs = [("127.0.0.1", 2000 + nodes_nr * 2)]
        await node.listen(2001 + i + nodes_nr * 2)
        await node.bootstrap(addrs)

        value = "my awesome value %d" % i
        key = "set from %d" % i
        await node.set(key, value)
        nodes.append(node)

    for i in range(nodes_nr):
        for node in nodes:
            value = "my awesome value %d" % i
            key = "set from %d" % i
            assert await node.get(key) == value
