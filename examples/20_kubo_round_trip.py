"""
Example 20: Real Kubo Round-Trip

This example demonstrates true interoperability with the official Go-based IPFS node (Kubo).
It connects `py-ipfs-lite` directly to a local Kubo daemon and performs a two-way Bitswap exchange,
demonstrating both DAG-JSON and UnixFS DAG-PB capabilities.
"""

import trio
import httpx
import logging
import json
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config
from libp2p.peer.peerinfo import info_from_p2p_addr
from multiaddr import Multiaddr

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("kubo_round_trip")

KUBO_API = "http://127.0.0.1:5001/api/v0"

async def check_kubo_running() -> dict:
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{KUBO_API}/id", timeout=2.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
    return None

async def main():
    logger.info("--- Kubo Interoperability Round-Trip ---")
    
    # 1. Check if Kubo is available
    logger.info("Checking for local Kubo daemon on port 5001...")
    kubo_id_info = await check_kubo_running()
    
    if not kubo_id_info:
        logger.error("❌ Kubo daemon is not running.")
        logger.error("Please install Kubo (https://docs.ipfs.tech/install/command-line/) and run `ipfs daemon` in another terminal.")
        return
        
    kubo_peer_id = kubo_id_info.get("ID")
    kubo_addresses = kubo_id_info.get("Addresses", [])
    
    # Find a local ipv4 address for kubo
    kubo_local_addr = None
    for addr in kubo_addresses:
        if "/ip4/127.0.0.1/tcp/" in addr:
            kubo_local_addr = addr
            break
            
    if not kubo_local_addr:
        logger.error("❌ Could not find a local IPv4 address for Kubo.")
        return
        
    logger.info(f"✅ Found Kubo daemon. Peer ID: {kubo_peer_id}")
    logger.info(f"Kubo local address: {kubo_local_addr}")
    
    # 2. Start py-ipfs-lite
    # We disable reprovider (interval=-1) to avoid KadDHT background noise
    # trying to provide to the local Kubo daemon (which only supports /ipfs/lan/kad/1.0.0 locally).
    config = Config(
        offline=True, 
        blockstore_type="memory", 
        use_ipni=False,
        reprovide_interval_seconds=-1
    )
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    
    try:
        py_peer_id = peer.host.id().to_base58()
        logger.info(f"\nStarted py-ipfs-lite. Peer ID: {py_peer_id}")
        
        # Connect Py to Kubo directly
        logger.info("Connecting py-ipfs-lite directly to Kubo...")
        maddr = Multiaddr(kubo_local_addr)
        kubo_info = info_from_p2p_addr(maddr)
        await peer.host.connect(kubo_info)
        logger.info("✅ Direct libp2p connection established!")
        
        async with httpx.AsyncClient() as client:
            # --- PHASE 1: Py -> Kubo (DAG-JSON) ---
            logger.info("\n--- Phase 1: Python writes (DAG-JSON), Kubo reads ---")
            py_payload = {"source": "py-ipfs-lite", "message": "Hello Kubo, this is Python!"}
            py_cid = await peer.add_node(py_payload, codec="dag-json")
            logger.info(f"Python generated DAG-JSON CID: {py_cid}")
            
            logger.info("Asking Kubo to fetch it over Bitswap...")
            resp = await client.post(f"{KUBO_API}/dag/get?arg={py_cid}", timeout=5.0)
            if resp.status_code == 200:
                kubo_read_data = resp.json()
                logger.info(f"✅ Kubo successfully fetched the data via Bitswap: {kubo_read_data}")
            else:
                logger.error(f"❌ Kubo failed to fetch: {resp.text}")
                
            # --- PHASE 2: Kubo -> Py (UnixFS DAG-PB) ---
            logger.info("\n--- Phase 2: Kubo writes (UnixFS), Python reads ---")
            kubo_payload = "Hello Python, this is Kubo via UnixFS DAG-PB!"
            
            logger.info("Adding file to Kubo...")
            files = {'file': ('hello.txt', kubo_payload.encode('utf-8'))}
            resp = await client.post(f"{KUBO_API}/add?cid-version=1", files=files)
            if resp.status_code == 200:
                lines = resp.text.strip().split('\n')
                kubo_cid = json.loads(lines[-1]).get("Hash")
                logger.info(f"Kubo generated UnixFS CID: {kubo_cid}")
                
                logger.info("Asking Python to fetch it over Bitswap...")
                py_read_data_bytes = await peer.get_file(kubo_cid, provider_addr=kubo_local_addr)
                py_read_data = py_read_data_bytes.decode('utf-8')
                
                logger.info(f"✅ Python successfully fetched the file via Bitswap: '{py_read_data}'")
            else:
                logger.error(f"❌ Kubo failed to write: {resp.text}")
                
    finally:
        await peer.close()
        logger.info("\nDemo complete. Shutting down py-ipfs-lite.")

if __name__ == "__main__":
    trio.run(main)
