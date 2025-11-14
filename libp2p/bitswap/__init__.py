"""
Bitswap protocol implementation for py-libp2p.

This module provides Bitswap v1.0.0, v1.1.0, and v1.2.0 implementations
for content discovery and file sharing, allowing peers to exchange
content-addressed blocks in a peer-to-peer network.
"""

from .block_store import BlockStore, MemoryBlockStore
from .client import BitswapClient
from . import config
from .cid import (
    compute_cid,
    compute_cid_v0,
    compute_cid_v1,
    get_cid_prefix,
    reconstruct_cid_from_prefix_and_data,
    verify_cid,
    parse_cid_version,
    cid_to_string,
    CID_V0,
    CID_V1,
    CODEC_DAG_PB,
    CODEC_RAW,
)
from .errors import (
    BitswapError,
    InvalidBlockError,
    BlockTooLargeError,
    MessageTooLargeError,
    TimeoutError,
    BlockNotFoundError,
    BlockUnavailableError,
    InvalidCIDError,
)

__all__ = [
    "BitswapClient",
    "BlockStore",
    "MemoryBlockStore",
    "config",
    # CID utilities
    "compute_cid",
    "compute_cid_v0",
    "compute_cid_v1",
    "get_cid_prefix",
    "reconstruct_cid_from_prefix_and_data",
    "verify_cid",
    "parse_cid_version",
    "cid_to_string",
    "CID_V0",
    "CID_V1",
    "CODEC_DAG_PB",
    "CODEC_RAW",
    # Errors
    "BitswapError",
    "InvalidBlockError",
    "BlockTooLargeError",
    "MessageTooLargeError",
    "TimeoutError",
    "BlockNotFoundError",
    "BlockUnavailableError",
    "InvalidCIDError",
]
