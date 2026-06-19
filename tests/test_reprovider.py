import pytest
import trio
from py_ipfs_lite.reprovider import Reprovider

class MockConfig:
    def __init__(self, strategy="all"):
        self.reprovider_strategy = strategy
        self.default_timeout = 30.0
        self.reprovide_interval_seconds = -1

class MockBlockstore:
    def all_keys(self):
        return ["cid1", "cid2"]

class MockPinStore:
    def get_pins(self, type_filter="all"):
        return {"cid1": "recursive"}

class MockRouting:
    def __init__(self):
        self.provided = []
    
    async def provide(self, cid_str: str):
        await trio.sleep(0)
        self.provided.append(cid_str)

class MockPeer:
    def __init__(self, strategy):
        self.config = MockConfig(strategy)
        self.blockstore = MockBlockstore()
        self.pin_store = MockPinStore()
        self.routing = MockRouting()

@pytest.mark.trio
async def test_reprovider_strategy_all():
    peer = MockPeer("all")
    reprovider = Reprovider(peer)
    
    await reprovider.reprovide()
    
    assert len(peer.routing.provided) == 2
    assert "cid1" in peer.routing.provided
    assert "cid2" in peer.routing.provided

@pytest.mark.trio
async def test_reprovider_strategy_pinned():
    peer = MockPeer("pinned")
    reprovider = Reprovider(peer)
    
    await reprovider.reprovide()
    
    assert len(peer.routing.provided) == 1
    assert "cid1" in peer.routing.provided

