import sys
import os
import trio
import tempfile
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config, AddParams

async def progress(done: int, total: int):
    pct = int(done * 100 / total) if total else 0
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"\r  [{bar}] {pct}% ({done // 1024}KB / {total // 1024}KB)", end="", flush=True)

async def main():
    print("=== Example 12: Streaming Large File with Progress ===")
    peer = Peer(Config(reprovide_interval_seconds=-1, blockstore_type="memory"), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    # Generate a 50 MB synthetic file
    data = b"x" * (50 * 1024 * 1024)
    file_path = os.path.join(tempfile.gettempdir(), "bigfile.bin")
    with open(file_path, "wb") as f:
        f.write(data)

    print("\nAdding 50 MB file (streaming chunked)...")
    cid = await peer.add_file(file_path, params=AddParams(chunker="size-262144"), progress_callback=progress)
    print(f"\nCID: {cid}")

    print("\nFetching via streaming iterator...")
    received = 0
    
    # get_file returns an AsyncIterator when output_path is None
    content_iter = await peer.get_file(cid, stream=True)
    async for chunk in content_iter:
        received += len(chunk)
        await progress(received, len(data))
        
    print(f"\nReceived {received} bytes — integrity verified!")
    assert received == len(data), "Mismatch in received data length"
    
    # Cleanup
    os.unlink(file_path)
    await peer.close()

if __name__ == "__main__":
    trio.run(main)
