import os
import subprocess
import trio
import tempfile
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config
from py_ipfs_lite.cli import DEFAULT_BOOTSTRAP_PEERS

async def main():
    print("=== Example 09: Kubo Interoperability ===")
    
    # 1. Create a local file to add
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"Hello from py-ipfs-lite! This is a test file for Kubo interop.")
        temp_path = f.name

    try:
        # Start py peer
        print("\nStarting py-ipfs-lite peer...")
        peer = Peer(Config(reprovide_interval_seconds=10), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
        await peer.start()
        
        # 2. Add file from Python
        print(f"Adding file {temp_path} to Python peer...")
        py_cid = await peer.add_file(temp_path)
        print(f"Python Peer added CID: {py_cid}")
        
        print("\nPython Peer ID:", peer.host.id())
        print("Python Peer Addresses:")
        for addr in peer.host.addrs():
            print(f"  {addr}")
            
        print("\nUsing local Kubo (ipfs) CLI to fetch it...")
        # To make this fast and reliable, we will have Kubo connect directly to our Python peer
        # instead of waiting for the global DHT.
        py_addr = str(peer.host.addrs()[0])
        
        # Ensure ipfs daemon is running or we can just use the ipfs CLI.
        # Actually, `ipfs cat` works without a daemon if we use `ipfs swarm connect` first?
        # No, `ipfs swarm connect` requires a daemon.
        # Let's just use `ipfs --api=/ip4/127.0.0.1/tcp/5001` assuming daemon is running, 
        # or we just try to fetch it globally.
        # But if the global network takes 30s to propagate DHT, let's use the local IPFS daemon.
        
        print(f"\nRun the following command in another terminal with an IPFS daemon running:")
        print(f"  ipfs swarm connect {py_addr}")
        print(f"  ipfs cat {py_cid}")
        
        try:
            # Check if daemon is running by connecting to it
            res = await trio.run_process(["ipfs", "swarm", "connect", py_addr], capture_stdout=True, capture_stderr=True)
            if res.returncode == 0:
                print(f"Automatically connected local Kubo daemon to Python peer!")
                print(f"Fetching CID from Python peer using Kubo...")
                cat_res = await trio.run_process(["ipfs", "cat", py_cid], capture_stdout=True, capture_stderr=True)
                print(f"Kubo fetched content: {cat_res.stdout.decode('utf-8').strip()}")
                
                print("\nNow adding a file to Kubo...")
                with tempfile.NamedTemporaryFile(delete=False) as f2:
                    f2.write(b"Hello from Kubo! This is a response.")
                    f2_path = f2.name
                    
                add_res = await trio.run_process(["ipfs", "add", "-Q", f2_path], capture_stdout=True, capture_stderr=True)
                kubo_cid = add_res.stdout.decode('utf-8').strip()
                print(f"Kubo added CID: {kubo_cid}")
                os.unlink(f2_path)
                
                print("\nFetching Kubo CID from Python peer...")
                # We are already connected, so Bitswap should just pull it
                data = await peer.get_file(kubo_cid)
                print(f"Python peer fetched content: {data.decode('utf-8').strip()}")
                print("\n✓ Interoperability test successful!")
            else:
                print("\nCould not automatically run Kubo. Make sure 'ipfs daemon' is running.")
                print(f"Error: {res.stderr.decode('utf-8')}")
        except FileNotFoundError:
            print("\nIPFS CLI not found. Please install Kubo (ipfs).")
            
    finally:
        os.unlink(temp_path)
        await peer.close()

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    trio.run(main)
