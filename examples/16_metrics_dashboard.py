import trio
import httpx
from prometheus_client import start_http_server
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    print("=== Example 16: Metrics Dashboard Integration ===")
    
    # Start Prometheus HTTP server on a background thread
    print("Starting Prometheus exporter on http://localhost:8000/metrics...")
    start_http_server(8000)
    
    # Create a peer (using memory blockstore)
    peer = Peer(Config(reprovide_interval_seconds=-1, blockstore_type="memory"), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    print("\nSimulating node activity to generate metrics...")
    # Add some nodes
    for i in range(50):
        await peer.add_node({"hello": f"world_{i}"}, codec="dag-cbor")
        
    print("Triggering Garbage Collection to populate GC metrics...")
    await peer.gc()
    
    print("\nFetching exported metrics from http://localhost:8000/metrics...")
    # Fetch metrics
    async with httpx.AsyncClient() as client:
        resp = await client.get("http://localhost:8000/metrics")
        lines = resp.text.split("\n")
        
        print("\n--- IPFS Node Metrics ---")
        for line in lines:
            if line.startswith("ipfs_") and not line.endswith("created"):
                print(f"  {line}")
                
    await peer.close()
    print("\n✓ Metrics successfully exported and scraped!")

if __name__ == "__main__":
    trio.run(main)
