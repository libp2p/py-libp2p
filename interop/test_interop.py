import io
import os
import subprocess
import pytest
import trio

from py_ipfs_lite.peer import Peer
from py_ipfs_lite.setup import setup_libp2p, new_in_memory_datastore
from libp2p.bitswap.cid import cid_to_text, parse_cid
from multiaddr import Multiaddr

GO_PEER_BIN = os.path.join(os.path.dirname(__file__), "go-peer", "go-peer")

@pytest.mark.trio
async def test_py_adds_go_fetches():
    host, routing = await setup_libp2p(
        host_key=None,
        secret=None,
        listen_addrs=["/ip4/127.0.0.1/tcp/0"],
        datastore=None
    )
    async with host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
        peer = await Peer.new(
            datastore=new_in_memory_datastore(),
            blockstore=None,
            host=host,
            routing=routing,
        )
        
        file_content = "Hello from Python IPFS Lite!"
        cid = await peer.add_file(file_content)
        cid_str = cid_to_text(cid)
        
        # Wait for the listener to bind to the port
        addrs = []
        for _ in range(10):
            addrs = host.get_addrs()
            if addrs:
                break
            await trio.sleep(0.1)
        
        if not addrs:
            pytest.fail("Host did not start listening")
            
        print("HOST ADDRS:", addrs)
        target_addr = str(addrs[0])
        print("TARGET ADDR:", target_addr)

        try:
            with trio.fail_after(20):
                process = await trio.lowlevel.open_process(
                    [GO_PEER_BIN, target_addr, "fetch", cid_str],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                
                async def read_stderr():
                    while True:
                        try:
                            line = await process.stderr.receive_some(1024)
                            if not line:
                                break
                            print("GO_PEER STDERR:", line.decode().strip())
                        except trio.ClosedResourceError:
                            break
                            
                async def read_stdout():
                    output_buffer = ""
                    while True:
                        try:
                            line = await process.stdout.receive_some(1024)
                            if not line:
                                break
                            output_buffer += line.decode()
                        except trio.ClosedResourceError:
                            break
                    return output_buffer

                async with trio.open_nursery() as nursery:
                    nursery.start_soon(read_stderr)
                    
                    output_str = ""
                    while True:
                        try:
                            line = await process.stdout.receive_some(1024)
                            if not line:
                                break
                            output_str += line.decode()
                        except trio.ClosedResourceError:
                            break
                    
                import re
                match = re.search(r"DONE_FETCH:\s*(.*)", output_str)
                if match:
                    fetched_content = match.group(1).strip()
                else:
                    pytest.fail(f"Could not find fetch output in go-peer stdout: {output_str}")
                    
                assert fetched_content == file_content
                
        except trio.TooSlowError:
            pytest.fail("Go peer timed out fetching")
        
        await peer.close()

@pytest.mark.trio
async def test_go_adds_py_fetches():
    host, routing = await setup_libp2p(
        host_key=None,
        secret=None,
        listen_addrs=["/ip4/127.0.0.1/tcp/0"],
        datastore=None
    )
    async with host.run([Multiaddr("/ip4/127.0.0.1/tcp/0")]):
        peer = await Peer.new(
            datastore=new_in_memory_datastore(),
            blockstore=None,
            host=host,
            routing=routing,
        )
        
        addrs = []
        for _ in range(10):
            addrs = host.get_addrs()
            if addrs:
                break
            await trio.sleep(0.1)
        
        if not addrs:
            pytest.fail("Host did not start listening")
            
        target_addr = str(addrs[0])
        
        file_content = "Hello from Go IPFS Lite!"

        try:
            with trio.fail_after(20):
                # Run Go peer to add file (it will sleep for 10s after adding)
                process = await trio.lowlevel.open_process(
                    [GO_PEER_BIN, target_addr, "add", file_content],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                
                # Read stdout until we see DONE_ADD
                cid_str = None
                output_buffer = ""
                while True:
                    line = await process.stdout.receive_some(1024)
                    if not line:
                        break
                    text = line.decode()
                    output_buffer += text
                    if "DONE_ADD:" in text:
                        cid_str = text.split("DONE_ADD:")[1].strip()
                        break

                assert cid_str is not None, "Failed to get CID from Go peer"
                
        except trio.TooSlowError:
            pytest.fail("Go peer timed out adding")
        
        cid = parse_cid(cid_str)
        
        retrieved_file = await peer.get_file(cid)
        fetched = retrieved_file.read().decode()
        assert fetched == file_content
        
        await peer.close()
