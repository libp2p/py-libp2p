"""
Example 17: Concurrent Multi-Agent Ingestion Benchmark

This example demonstrates the robustness of the py-ipfs-lite GC and blockstore locking
under heavy concurrent load. We simulate multiple "agents" generating and pinning IPLD
knowledge nodes concurrently, while a background task periodically triggers GC.
"""

import trio
import time
import uuid
import logging
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("benchmark")

NUM_AGENTS = 10
NODES_PER_AGENT = 100

async def agent_task(agent_id: int, peer: Peer, start_event: trio.Event, total_cids: list):
    """Simulates an AI agent continuously writing memory to IPFS."""
    await start_event.wait()
    logger.info(f"Agent {agent_id} starting ingestion...")
    
    agent_cids = []
    start_time = time.time()
    
    for i in range(NODES_PER_AGENT):
        payload = {
            "agent_id": agent_id,
            "memory_sequence": i,
            "content": f"Simulated memory chunk {uuid.uuid4()}",
            "timestamp": time.time()
        }
        
        # Add the node to IPFS (which internally pins it by default)
        cid = await peer.add_node(payload, codec="dag-json")
        agent_cids.append(cid)
        
        # Small sleep to yield to event loop simulating processing time
        await trio.sleep(0.01)

    duration = time.time() - start_time
    logger.info(f"Agent {agent_id} finished {NODES_PER_AGENT} nodes in {duration:.2f}s ({NODES_PER_AGENT/duration:.1f} nodes/sec)")
    total_cids.extend(agent_cids)

async def gc_task(peer: Peer, stop_event: trio.Event):
    """Simulates aggressive background garbage collection."""
    await trio.sleep(0.5) # Wait for ingestion to start
    runs = 0
    while not stop_event.is_set():
        logger.warning(f"--- Triggering aggressive background GC (run {runs}) ---")
        try:
            reclaimed = await peer.gc()
            logger.warning(f"--- GC complete. Reclaimed {reclaimed.reclaimed_blocks} blocks. ---")
        except Exception as e:
            logger.error(f"GC failed: {e}")
        runs += 1
        await trio.sleep(0.5)

async def main():
    config = Config(
        offline=True, 
        blockstore_type="memory",
        use_ipni=False
    )
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    
    await peer.start()
    logger.info("Peer started. Initializing Benchmark...")
    
    start_event = trio.Event()
    stop_event = trio.Event()
    total_cids = []
    
    global_start = time.time()
    
    try:
        async with trio.open_nursery() as root_nursery:
            # Spawn the background GC daemon
            root_nursery.start_soon(gc_task, peer, stop_event)
            
            # Spawn agents in a sub-nursery so we can wait for them to finish
            async with trio.open_nursery() as agent_nursery:
                for i in range(NUM_AGENTS):
                    agent_nursery.start_soon(agent_task, i, peer, start_event, total_cids)
                
                # Unleash the agents
                logger.info(f"Unleashing {NUM_AGENTS} concurrent agents...")
                start_event.set()
                
            # When agent_nursery exits, all agents are done!
            stop_event.set()
            
    finally:
        await peer.close()

    total_time = time.time() - global_start
    total_nodes = NUM_AGENTS * NODES_PER_AGENT
    
    logger.info("=" * 50)
    logger.info("BENCHMARK COMPLETE")
    logger.info(f"Total Nodes Ingested: {total_nodes}")
    logger.info(f"Unique CIDs captured: {len(set(total_cids))}")
    logger.info(f"Total Time: {total_time:.2f}s")
    logger.info(f"Aggregate Throughput: {total_nodes/total_time:.2f} nodes/sec")
    logger.info("=" * 50)

if __name__ == "__main__":
    trio.run(main)
