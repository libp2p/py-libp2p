"""
Bitswap protocol implementation for py-libp2p.

This module provides Bitswap v1.0.0, v1.1.0, and v1.2.0 implementations
for content discovery and file sharing, allowing peers to exchange
content-addressed blocks in a peer-to-peer network.

Public API overview
-------------------
**Preferred (py-cid-native) APIs** – use these for new code:

- ``parse_cid``            – parse any CID form into a ``CIDObject``
- ``compute_cid_v1_obj``   – produce a v1 ``CIDObject`` directly
- ``compute_cid_v0_obj``   – produce a v0 ``CIDObject`` directly
- ``compute_cid_obj``      – auto-select v0/v1 and return ``CIDObject``
- ``cid_to_text``          – canonical base-encoded string from any CID input
- ``format_cid_for_display``– human-friendly CID display with optional truncation
- ``CIDInput``             – accepted input union (``bytes | str | CIDObject``)
- ``CIDObject``            – ``py-cid`` object type alias (``CIDv0 | CIDv1``)

**Backward-compatible APIs** – still supported, return raw ``bytes``:

- ``compute_cid_v1``       – returns CID as raw ``bytes``
- ``compute_cid_v0``       – returns CID as raw ``bytes``
- ``compute_cid``          – auto-select v0/v1, returns ``bytes``
- ``cid_to_bytes``         – normalise any CID input to ``bytes``
- ``verify_cid``           – verify data against a CID (accepts ``CIDInput``)
- ``get_cid_prefix``       – extract CID prefix bytes (accepts ``CIDInput``)

These byte-returning helpers remain to avoid breaking existing callers.
New code should prefer the object-returning variants above.
"""

from .block_store import BlockStore, MemoryBlockStore
from .cid import (
    CID_V0,
    CID_V1,
    CODEC_DAG_PB,
    CODEC_RAW,
    CIDInput,
    CIDObject,
    cid_to_bytes,
    cid_to_text,
    compute_cid,
    compute_cid_obj,
    compute_cid_v0,
    compute_cid_v0_obj,
    compute_cid_v1,
    compute_cid_v1_obj,
    format_cid_for_display,
    get_cid_prefix,
    parse_cid,
    parse_cid_codec,
    reconstruct_cid_from_prefix_and_data,
    verify_cid,
)
from .client import BitswapClient
from .errors import (
    BitswapError,
    BlockNotFoundError,
    BlockTooLargeError,
    BlockUnavailableError,
    InvalidBlockError,
    InvalidCIDError,
    MessageTooLargeError,
    TimeoutError,
)

__all__ = [
    # Core
    "BitswapClient",
    "BlockStore",
    "MemoryBlockStore",
    # CID types
    "CIDInput",
    "CIDObject",
    # CID preferred (object) APIs
    "parse_cid",
    "compute_cid_obj",
    "compute_cid_v0_obj",
    "compute_cid_v1_obj",
    "cid_to_text",
    "format_cid_for_display",
    "parse_cid_codec",
    # CID backward-compatible (bytes) APIs
    "compute_cid",
    "compute_cid_v0",
    "compute_cid_v1",
    "cid_to_bytes",
    "verify_cid",
    "get_cid_prefix",
    "reconstruct_cid_from_prefix_and_data",
    # CID constants
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
