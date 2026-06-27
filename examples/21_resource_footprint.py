"""Example 21: Resource-Constrained Footprint.

Demonstrates the minimal CPU and Memory footprint of a py-ipfs-lite node.
This backs up the "lite" claim, proving it can be embedded in resource-constrained
environments like a Raspberry Pi, edge device, or a small Docker container.
"""

import logging
import os
import time

import psutil
import trio

from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("footprint")


def print_usage(label: str):
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    rss_mb = mem_info.rss / (1024 * 1024)
    cpu_percent = process.cpu_percent(interval=0.1)  # short block to get realistic CPU%
    logger.info(
        f"[{label:^20}] Memory (RSS): {rss_mb:.2f} MB | CPU: {cpu_percent:.1f}%"
    )


async def main():
    logger.info("--- Py-IPFS-Lite Resource Footprint Demo ---")

    # Initialize CPU counter
    psutil.Process(os.getpid()).cpu_percent(interval=None)

    print_usage("Baseline (Python)")

    config = Config(offline=True, blockstore_type="memory", use_ipni=False)
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])

    await peer.start()
    await trio.sleep(1)  # Let background tasks settle
    print_usage("Peer Idle")

    try:
        logger.info("\nSimulating Load: Rapidly ingesting 5000 nodes...")
        start_time = time.time()

        for i in range(5000):
            await peer.add_node({"node_index": i, "data": "X" * 128}, codec="dag-json")
            if i > 0 and i % 1000 == 0:
                print_usage(f"Ingesting ({i})")

        elapsed = time.time() - start_time
        logger.info(f"Ingested 5000 nodes in {elapsed:.2f} seconds.")
        print_usage("Peak Load")

        logger.info("\nTriggering Garbage Collection...")
        res = await peer.gc()
        logger.info(f"GC Reclaimed {res.reclaimed_blocks} blocks.")

        await trio.sleep(1)
        print_usage("Post-GC")

    finally:
        await peer.close()

    print_usage("Teardown")


if __name__ == "__main__":
    trio.run(main)
