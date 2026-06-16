import io

import pytest

from py_ipfs_lite.peer import Peer
from py_ipfs_lite.setup import new_in_memory_datastore, setup_libp2p


@pytest.mark.trio
async def test_dag_operations():
    host, routing = await setup_libp2p(
        host_key=None,
        secret=None,
        listen_addrs=["/ip4/127.0.0.1/tcp/0"],
        datastore=None
    )
    peer = await Peer.new(
        datastore=new_in_memory_datastore(),
        blockstore=None,
        host=host,
        routing=routing,
    )
    
    node = {"data": "test_node"}
    cid = await peer.add(node)
    
    assert cid is not None
    assert await peer.has_block(cid)
    
    retrieved = await peer.get(cid)
    import json
    assert json.loads(retrieved) == node
    
    await peer.remove(cid)
    assert not await peer.has_block(cid)
    await peer.close()

@pytest.mark.trio
async def test_file_operations():
    host, routing = await setup_libp2p(
        host_key=None,
        secret=None,
        listen_addrs=["/ip4/127.0.0.1/tcp/0"],
        datastore=None
    )
    peer = await Peer.new(
        datastore=new_in_memory_datastore(),
        blockstore=None,
        host=host,
        routing=routing,
    )
    
    # Test with string source
    file_content = "hello world"
    cid1 = await peer.add_file(file_content)
    
    retrieved_file = await peer.get_file(cid1)
    assert retrieved_file is not None
    assert retrieved_file.read() == b"hello world"
    
    # Test with bytes IO source
    bytes_content = b"hello bytes"
    source = io.BytesIO(bytes_content)
    cid2 = await peer.add_file(source)
    
    retrieved_bytes_file = await peer.get_file(cid2)
    assert retrieved_bytes_file is not None
    assert retrieved_bytes_file.read() == b"hello bytes"
    await peer.close()
