"""Example 19: AI Agent Filecoin Pipeline (CAR → ProPGF M1).

This example demonstrates how an AI agent can build a cryptographically
verifiable log of its inference steps (prompts, tool calls, thoughts)
as a native IPLD Merkle DAG, and export that complete trace into a
Filecoin-ready .car file natively, without relying on an external Kubo daemon.
"""

import logging
import os

import trio

from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("filecoin_pipeline")


async def main():
    logger.info("--- AI Agent Verifiable Inference Pipeline ---")

    # 1. Initialize local, offline py-ipfs-lite peer
    # We use a memory blockstore to prove we don't need a heavy local disk setup
    config = Config(offline=True, blockstore_type="memory", use_ipni=False)
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])

    await peer.start()

    try:
        # 2. Simulate AI Inference Steps (building a Merkle DAG)
        logger.info("\n1. Agent executing inference steps and logging to IPLD...")

        # Step 1: User Prompt
        step_1_cid = await peer.add_node(
            {"type": "user_prompt", "content": "What is the weather in Tokyo?"},
            codec="dag-json",
        )
        logger.info(f"  -> Logged Step 1: {step_1_cid}")

        # Step 2: Tool Call
        step_2_cid = await peer.add_node(
            {
                "type": "tool_call",
                "tool": "get_weather",
                "args": {"location": "Tokyo"},
                # IPLD Link to previous step
                "previous_step": {"/": step_1_cid},
            },
            codec="dag-json",
        )
        logger.info(f"  -> Logged Step 2: {step_2_cid}")

        # Step 3: Tool Result
        step_3_cid = await peer.add_node(
            {
                "type": "tool_result",
                "result": "Heavy Rain",
                "previous_step": {"/": step_2_cid},
            },
            codec="dag-json",
        )
        logger.info(f"  -> Logged Step 3: {step_3_cid}")

        # Step 4: Final Response (Root Node)
        root_cid = await peer.add_node(
            {
                "type": "agent_response",
                "content": "It is currently raining heavily in Tokyo.",
                "previous_step": {"/": step_3_cid},
            },
            codec="dag-json",
        )
        logger.info(f"  -> Logged Final Response (Root): {root_cid}")

        logger.info("\nInference DAG successfully constructed in-memory.")

        # 3. Export to Filecoin-ready CAR file
        car_filename = "agent_inference_trace.car"
        logger.info(f"\n2. Exporting complete cryptographic trace to {car_filename}...")

        await peer.export_car(root_cid, car_filename)

        # Verify the export
        if os.path.exists(car_filename):
            size = os.path.getsize(car_filename)
            logger.info(
                f"\n✅ SUCCESS: Created Filecoin-ready CAR archive ({size} bytes)."
            )
            logger.info(
                f"This file contains the complete verifiable inference history for root CID {root_cid}."
            )
            logger.info(
                "It is perfectly formatted to be imported into a Filecoin Storage Provider (e.g. `lotus client import --car agent_inference_trace.car`)."
            )
        else:
            logger.error("\n❌ FAILED: CAR file was not created.")

    finally:
        await peer.close()

    # Clean up the file so we don't litter the repo
    # (Commented out for the demo so the user can show the CAR file)
    # if os.path.exists(car_filename):
    #     os.remove(car_filename)


if __name__ == "__main__":
    trio.run(main)
