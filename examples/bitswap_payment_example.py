"""
Example: Bitswap 1.3.0 with Root CID Payment System

Demonstrates how to set up a payment-gated Bitswap server that charges
for files at the root CID level (not per-block), using the new payment
infrastructure.

Key Features:
- Payment required only for root CID (all chunks accessible after payment)
- Configurable pricing: free, fixed, or size-based
- EIP-3009 meta-transaction support (off-chain payment authorization)
- Automatic DAG registration for multi-block files

Usage:
    # Start payment-gated server
    python examples/bitswap_payment_server.py --price-per-mb 0.01
    
    # Start client
    python examples/bitswap_payment_client.py --server /ip4/127.0.0.1/tcp/4001/p2p/...
"""

import asyncio
import logging
from pathlib import Path

from libp2p import new_host
from libp2p.bitswap import (
    BitswapClient,
    FilesystemBlockStore,
    MerkleDag,
    PaymentGatedDecisionEngine,
)
from libp2p.bitswap.payment_ledger import PaymentLedger
from libp2p.bitswap.pricing_engine import BlockPricingEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def setup_payment_server(
    price_per_mb: float = 0.01,  # $0.01 per MB
    wallet_address: str = "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
) -> tuple[BitswapClient, PaymentGatedDecisionEngine, MerkleDag]:
    """
    Set up a payment-gated Bitswap server.
    
    Args:
        price_per_mb: Price in USD per megabyte
        wallet_address: Ethereum address to receive payments
        
    Returns:
        (bitswap_client, payment_engine, dag)
    """
    # Create libp2p host
    host = new_host()
    await host.run(["/ip4/0.0.0.0/tcp/4001"])
    
    # Create block store
    store = FilesystemBlockStore(Path("./bitswap_data"))
    
    # Create payment ledger (tracks who has paid for what)
    ledger = PaymentLedger()
    
    # Create pricing engine (size-based: price scales with file size)
    # Convert $/MB to micro-units/KB: $0.01/MB = 10,000 micro-units/MB = 10 micro-units/KB
    units_per_kb = (price_per_mb * 1_000_000) / 1024
    pricing = BlockPricingEngine(
        strategy="size_based",
        units_per_kb=units_per_kb,
    )
    
    # Create payment-gated decision engine
    payment_engine = PaymentGatedDecisionEngine(
        blockstore=store,
        ledger=ledger,
        pricing=pricing,
        tx_verifier=None,  # Optional: add EIP-3009 verifier
        server_wallet=wallet_address,
        network="sepolia",
        asset="USDC",
    )
    
    # Create Bitswap client with payment engine
    bitswap = BitswapClient(
        host=host,
        block_store=store,
        protocol_version="/ipfs/bitswap/1.3.0",
        payment_engine=payment_engine,
    )
    await bitswap.start()
    
    # Create DAG manager
    dag = MerkleDag(bitswap, block_store=store)
    
    logger.info(f"✅ Payment-gated server started")
    logger.info(f"   Address: {host.get_id()}")
    logger.info(f"   Pricing: ${price_per_mb:.4f}/MB = {units_per_kb:.2f} units/KB")
    logger.info(f"   Wallet: {wallet_address}")
    
    return bitswap, payment_engine, dag


async def add_paid_file(
    dag: MerkleDag,
    payment_engine: PaymentGatedDecisionEngine,
    file_path: Path,
) -> str:
    """
    Add a file that requires payment to access.
    
    Args:
        dag: MerkleDag instance
        payment_engine: Payment engine for DAG registration
        file_path: Path to file to add
        
    Returns:
        Root CID (hex string)
    """
    logger.info(f"📤 Adding paid file: {file_path}")
    
    # Add file to Bitswap (auto-chunks large files)
    root_cid = await dag.add_file(str(file_path))
    
    # Get all CIDs in the DAG (root + children)
    # In a real implementation, you'd get this from the DAG add operation
    # For now, we'll assume it's just the root CID
    all_cids = [root_cid]
    file_size = file_path.stat().st_size
    
    # Register DAG for root CID payment tracking
    await payment_engine.register_dag(
        root_cid=root_cid,
        child_cids=all_cids[1:],  # Exclude root from children
        total_size=file_size,
    )
    
    logger.info(f"✅ File added: {root_cid.hex()[:20]}... ({file_size} bytes)")
    return root_cid.hex()


async def add_free_file(
    dag: MerkleDag,
    payment_engine: PaymentGatedDecisionEngine,
    file_path: Path,
) -> str:
    """
    Add a file that is free to access (no payment required).
    
    Args:
        dag: MerkleDag instance
        payment_engine: Payment engine for marking free
        file_path: Path to file to add
        
    Returns:
        Root CID (hex string)
    """
    logger.info(f"📤 Adding free file: {file_path}")
    
    # Add file to Bitswap
    root_cid = await dag.add_file(str(file_path))
    
    # Mark as free (no payment required)
    payment_engine.mark_free(root_cid)
    
    file_size = file_path.stat().st_size
    logger.info(f"✅ Free file added: {root_cid.hex()[:20]}... ({file_size} bytes)")
    return root_cid.hex()


async def main():
    """Example usage."""
    # Set up payment-gated server
    bitswap, payment_engine, dag = await setup_payment_server(
        price_per_mb=0.01,  # $0.01 per MB
        wallet_address="0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",
    )
    
    # Add some files
    # Example 1: Paid file (5 MB = $0.05)
    # paid_cid = await add_paid_file(
    #     dag, payment_engine, Path("./large_file.bin")
    # )
    
    # Example 2: Free file (always accessible)
    # free_cid = await add_free_file(
    #     dag, payment_engine, Path("./readme.txt")
    # )
    
    logger.info("Server running. Press Ctrl+C to stop.")
    
    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await bitswap.stop()


if __name__ == "__main__":
    asyncio.run(main())
