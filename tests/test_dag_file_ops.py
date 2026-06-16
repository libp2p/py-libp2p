import io

import pytest

from py_ipfs_lite.peer import Peer
from py_ipfs_lite.setup import new_in_memory_datastore


@pytest.mark.trio
async def test_dag_operations():
    peer = await Peer.new(
        datastore=new_in_memory_datastore(),
        blockstore={},
        host=None,
        routing=None,
    )
    
    node = {"data": "test_node"}
    cid = await peer.add(node)
    
    assert cid is not None
    assert await peer.has_block(cid)
    
    retrieved = await peer.get(cid)
    assert retrieved == node
    
    await peer.remove(cid)
    assert not await peer.has_block(cid)

@pytest.mark.trio
async def test_file_operations():
    peer = await Peer.new(
        datastore=new_in_memory_datastore(),
        blockstore={},
        host=None,
        routing=None,
    )
    
    # Test with string source
    file_content = "hello world"
    cid1 = await peer.add_file(file_content)
    
    retrieved_file = await peer.get_file(cid1)
    assert retrieved_file is not None
    assert retrieved_file.read() == "hello world"
    
    # Test with bytes IO source
    bytes_content = b"hello bytes"
    source = io.BytesIO(bytes_content)
    cid2 = await peer.add_file(source)
    
    retrieved_bytes_file = await peer.get_file(cid2)
    assert retrieved_bytes_file is not None
    assert retrieved_bytes_file.read() == b"hello bytes"
