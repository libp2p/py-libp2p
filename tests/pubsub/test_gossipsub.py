import multiaddr
import pytest

from tests.utils import cleanup
from libp2p import new_node
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.gossipsub import GossipSub


@pytest.mark.asyncio
async def test_init():
    node = await new_node(transport_opt=["/ip4/127.0.0.1/tcp/0"])

    await node.get_network().listen(multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0"))

    supported_protocols = ["/gossipsub/1.0.0"]

    gossipsub = GossipSub(supported_protocols, 3, 2, 4, 30)
    pubsub = Pubsub(node, gossipsub, "a")

    # Did it work?
    assert gossipsub and pubsub

    await cleanup()
