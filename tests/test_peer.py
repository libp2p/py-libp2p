import os
import tempfile
import pytest
import trio
from multiaddr import Multiaddr

from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

@pytest.fixture
def memory_config():
    return Config(
        blockstore_type="memory",
        reprovide_interval_seconds=-1  # Disable reprovider for quick tests
    )

@pytest.fixture
def fs_config():
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Config(
            blockstore_type="filesystem",
            blockstore_path=tmpdirname,
            reprovide_interval_seconds=-1
        )

@pytest.mark.trio
async def test_peer_lifecycle(memory_config):
    peer = Peer(memory_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    assert peer._started is True
    assert len(peer.host.addrs()) > 0
    await peer.close()
    assert peer._started is False

@pytest.mark.trio
async def test_add_get_remove_node(memory_config):
    peer = Peer(memory_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    
    # 1. Add
    node_data = {"msg": "hello from node test"}
    cid_str = await peer.add_node(node_data, codec="dag-json")
    assert cid_str is not None
    
    # 2. Get
    fetched = await peer.get_node(cid_str)
    assert fetched == node_data
    assert await peer.has_block(cid_str) is True
    
    # 3. Remove
    await peer.remove_node(cid_str)
    from libp2p.bitswap.cid import parse_cid
    assert not await peer.blockstore.has(parse_cid(cid_str))
        
    await peer.close()

@pytest.mark.trio
async def test_add_get_file(memory_config):
    peer = Peer(memory_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"hello world")
        temp_path = f.name
        
    try:
        cid_str = await peer.add_file(temp_path)
        assert cid_str is not None
        
        content_iter = await peer.get_file(cid_str, stream=True)
        chunks = []
        async for chunk in content_iter:
            chunks.append(chunk)
        content = b"".join(chunks)
        assert content == b"hello world"
    finally:
        os.unlink(temp_path)
        
    await peer.close()

@pytest.mark.trio
async def test_pin_and_gc(memory_config):
    peer = Peer(memory_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    
    # Add two nodes
    cid1 = await peer.add_node({"name": "pinned"})
    cid2 = await peer.add_node({"name": "unpinned"})
    
    # Pin cid1
    await peer.add_pin(cid1, recursive=False)
    
    # GC
    stats = await peer.gc()
    
    # cid1 should exist, cid2 should be gone
    from libp2p.bitswap.cid import parse_cid
    assert await peer.blockstore.has(parse_cid(cid1))
    assert not await peer.blockstore.has(parse_cid(cid2))
        
    await peer.close()

@pytest.mark.trio
async def test_filesystem_blockstore(fs_config):
    peer = Peer(fs_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    
    cid_str = await peer.add_node({"foo": "bar"})
    assert cid_str is not None
    
    fetched = await peer.get_node(cid_str)
    assert fetched == {"foo": "bar"}
    
    await peer.close()
    
    assert os.path.exists(fs_config.blockstore_path)

def test_init_exports():
    from py_ipfs_lite import Peer, Config, AddParams
    assert Peer is not None
    assert Config is not None
    assert AddParams is not None

@pytest.mark.trio
async def test_add_file_with_params(memory_config):
    peer = Peer(memory_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    
    from py_ipfs_lite.config import AddParams
    params = AddParams(chunker="size-1024")
    
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"a" * 2048)
        temp_path = f.name
        
    try:
        cid_str = await peer.add_file(temp_path, params=params)
        assert cid_str is not None
        
        content_iter = await peer.get_file(cid_str, stream=True)
        chunks = []
        async for chunk in content_iter:
            chunks.append(chunk)
        content = b"".join(chunks)
        assert content == b"a" * 2048
    finally:
        os.unlink(temp_path)
        await peer.close()

@pytest.mark.trio
async def test_gc_concurrency_lock(memory_config):
    peer = Peer(memory_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"large data block " * 1000)
        temp_path = f.name
        
    try:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(peer.add_file, temp_path)
            nursery.start_soon(peer.gc)
    finally:
        os.unlink(temp_path)
        await peer.close()

@pytest.mark.trio
async def test_add_file_progress_callback(memory_config):
    peer = Peer(memory_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"hello progress callback")
        temp_path = f.name
        
    progress_updates = []
    def my_progress(written: int, total: int):
        progress_updates.append((written, total))
        
    try:
        cid_str = await peer.add_file(temp_path, progress_callback=my_progress)
        assert cid_str is not None
        assert len(progress_updates) > 0
        # The last update should have written == total
        assert progress_updates[-1][0] == progress_updates[-1][1]
        assert progress_updates[-1][1] == len(b"hello progress callback")
    finally:
        os.unlink(temp_path)
        
    await peer.close()

@pytest.mark.trio
async def test_api_parity_methods():
    from py_ipfs_lite import setup_libp2p, default_bootstrap_peers, new_in_memory_datastore
    from libp2p.crypto.ed25519 import create_new_key_pair
    from multiaddr import Multiaddr

    # Test helpers
    boot_peers = default_bootstrap_peers()
    assert isinstance(boot_peers, list)
    assert len(boot_peers) > 0

    mem_store = new_in_memory_datastore()
    assert mem_store is not None

    key_pair = create_new_key_pair()
    host, routing = await setup_libp2p(key_pair, ["/ip4/127.0.0.1/tcp/0"], offline=True)
    assert host is not None
    assert routing is None  # Since offline is True

def test_peer_accessors(memory_config):
    from py_ipfs_lite.peer import Peer
    peer = Peer(memory_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    
    # Initialize properties manually to avoid full async start() overhead in this test
    peer.blockstore = peer._create_blockstore()
    peer._exchange = "dummy_exchange"
    
    # Test accessors
    assert peer.session() == peer
    assert peer.block_store() is not None
    assert peer.exchange() == "dummy_exchange"
