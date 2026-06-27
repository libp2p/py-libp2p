import pytest
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

from py_ipfs_lite.routing import DelegatedHTTPRouting, TieredRouting


@pytest.mark.trio
async def test_delegated_routing():
    routing = DelegatedHTTPRouting("https://cid.contact")

    # Random nonexistent CID
    cid = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3dfuylqabf3oclgtqy55fbzdi"
    providers = await routing.find_providers(cid)

    assert isinstance(providers, list)

    await routing.close()


@pytest.mark.trio
async def test_tiered_routing():
    id1 = ID.from_base58("12D3KooWCvVxG5SBv5fZNVULQGpJuhBCiRNAABs24QqyxtEYy1Pv")
    id2 = ID.from_base58("12D3KooWAYwxFEW8ii71Xk8kM6vSdSTCBRiJm61AVnQP6YncZ7Nj")
    p1 = PeerInfo(id1, [])
    p2 = PeerInfo(id2, [])

    class DummyRouter1:
        async def find_providers(self, key, count=20):
            return [p1]

        async def provide(self, key):
            return True

        async def close(self):
            pass

    class DummyRouter2:
        async def find_providers(self, key, count=20):
            return [p2]

        async def provide(self, key):
            return False

        async def close(self):
            pass

    tiered = TieredRouting([DummyRouter1(), DummyRouter2()])

    providers = await tiered.find_providers("test")
    assert len(providers) == 2
    assert providers[0] == p1
    assert providers[1] == p2

    provided = await tiered.provide("test")
    assert provided is True
