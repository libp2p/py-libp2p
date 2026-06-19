import os
import tempfile
import pytest
import trio
from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer

@pytest.fixture
def fs_config():
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Config(
            blockstore_type="filesystem",
            blockstore_path=tmpdirname,
            reprovide_interval_seconds=-1
        )

@pytest.mark.trio
async def test_car_export_import(fs_config):
    peer = Peer(fs_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    # 1. create a file and a DAG node
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"hello car")
        temp_path = f.name
        
    try:
        file_cid = await peer.add_file(temp_path)
        
        node_data = {"links": [{"/": file_cid}], "msg": "test"}
        node_cid = await peer.add_node(node_data)
        
        # 2. export the CAR
        car_path = os.path.join(fs_config.blockstore_path, "test.car")
        await peer.export_car(node_cid, car_path)
        assert os.path.exists(car_path)
        assert os.path.getsize(car_path) > 0
        
        # 3. Create a second peer
        with tempfile.TemporaryDirectory() as tmpdirname2:
            config2 = Config(
                blockstore_type="filesystem",
                blockstore_path=tmpdirname2,
                reprovide_interval_seconds=-1
            )
            peer2 = Peer(config2, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
            await peer2.start()
            
            try:
                # 4. Import the CAR
                roots = await peer2.import_car(car_path)
                
                # 5. verify
                assert len(roots) == 1
                assert roots[0] == node_cid
                
                # Should be able to get the node
                fetched_node = await peer2.get_node(node_cid)
                assert fetched_node["msg"] == "test"
                
                # Should be able to get the file
                content = await peer2.get_file(file_cid)
                data = b""
                async for chunk in content:
                    data += chunk
                assert data == b"hello car"
            finally:
                await peer2.close()
    finally:
        os.unlink(temp_path)
        await peer.close()
