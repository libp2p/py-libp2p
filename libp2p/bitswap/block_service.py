"""
BlockService: transparent local→network fallback for block retrieval.

Sits between MerkleDag and BitswapClient, providing:
  - Local-first lookup (no network cost if block is already stored)
  - Automatic caching of network-fetched blocks into the local store
  - Peer announcement when new blocks are stored locally
  - A clean abstraction so MerkleDag is not hardwired to BitswapClient
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .block_store import BlockStore
from .cid import CIDInput, cid_to_bytes, format_cid_for_display, parse_cid

if TYPE_CHECKING:
    from libp2p.peer.id import ID as PeerID

    from .client import BitswapClient

logger = logging.getLogger(__name__)


class BlockService:
    """
    Combines a local BlockStore with a BitswapClient into one unified interface.

    get_block() flow:
        1. Check local BlockStore  →  return immediately if found (no network)
        2. Fetch via BitswapClient →  goes to the network
        3. Auto-cache the result   →  store locally so next call is free

    put_block() flow:
        1. Write to local BlockStore
        2. Call bitswap.add_block() so peers who have this CID in their
           wantlist are notified and can receive it

    This is a drop-in wrapper: MerkleDag can use BlockService instead of
    calling bitswap directly, and the behaviour is identical but with the
    caching and announcement benefits added transparently.

    Example:
        >>> store = FilesystemBlockStore("./blocks")
        >>> service = BlockService(store, bitswap)
        >>> dag = MerkleDag(bitswap, block_service=service)

    """

    def __init__(self, store: BlockStore, bitswap: BitswapClient) -> None:
        self.store = store
        self.bitswap = bitswap

    async def get_block(
        self,
        cid: CIDInput,
        peer_id: PeerID | None = None,
        timeout: float = 30.0,
    ) -> bytes | None:
        """
        Get a block. Checks local store first, then fetches from network.
        Any block fetched from the network is automatically cached locally.

        Args:
            cid: The CID of the block to retrieve
            peer_id: Optional specific peer to fetch from (passed to bitswap)
            timeout: Network timeout in seconds

        Returns:
            Block data bytes, or None if not found anywhere

        """
        cid_bytes = cid_to_bytes(cid)
        cid_obj = parse_cid(cid_bytes)

        # 1. Local lookup — instant, no network cost
        data = await self.store.get_block(cid_obj)
        if data is not None:
            logger.debug(
                f"BlockService: local hit {format_cid_for_display(cid_obj, max_len=12)}"
            )
            return data

        # 2. Network fetch via Bitswap
        logger.debug(
            f"BlockService: local miss, fetching from network "
            f"{format_cid_for_display(cid_obj, max_len=12)}"
        )
        try:
            data = await self.bitswap.get_block(cid_bytes, peer_id, timeout)
        except Exception as e:
            logger.warning(f"BlockService: network fetch failed: {e}")
            return None

        if data is not None:
            # 3. Auto-cache locally — future requests for this block are free
            await self.store.put_block(cid_obj, data)
            logger.debug(
                f"BlockService: cached fetched block "
                f"{format_cid_for_display(cid_obj, max_len=12)}"
            )

        return data

    async def put_block(self, cid: CIDInput, data: bytes) -> None:
        """
        Store a block locally and announce it to waiting peers.

        Calling bitswap.add_block() both writes to bitswap's own store AND
        notifies any peers who have this CID in their pending wantlist.
        We also write to our own store so get_block() local-hits on it.

        Args:
            cid: The CID of the block
            data: The block data bytes

        """
        cid_obj = parse_cid(cid_to_bytes(cid))

        # Write to our local store
        await self.store.put_block(cid_obj, data)

        # add_block() writes to bitswap's internal store AND calls
        # _notify_peers_about_block() for any peers waiting on this CID
        await self.bitswap.add_block(cid_obj, data)

        logger.debug(
            f"BlockService: stored and announced "
            f"{format_cid_for_display(cid_obj, max_len=12)}"
        )

    async def get_blocks_batch(
        self,
        cids: list[CIDInput],
        peer_id: PeerID | None = None,
        timeout: float = 30.0,
        batch_size: int = 32,
    ) -> dict[bytes, bytes]:
        """
        Batch-fetch multiple blocks. Local hits are returned immediately;
        only missing blocks go to the network. All network-fetched blocks
        are auto-cached locally.

        Args:
            cids: List of CIDs to fetch
            peer_id: Optional specific peer to fetch from
            timeout: Network timeout in seconds
            batch_size: Wantlist batch size passed to bitswap

        Returns:
            Dict mapping cid_bytes -> block_data for all found blocks

        """
        results: dict[bytes, bytes] = {}
        missing_cids: list[CIDInput] = []

        # Local pass first
        for cid in cids:
            cid_bytes = cid_to_bytes(cid)
            cid_obj = parse_cid(cid_bytes)
            data = await self.store.get_block(cid_obj)
            if data is not None:
                results[cid_bytes] = data
            else:
                missing_cids.append(cid)

        if not missing_cids:
            logger.debug(f"BlockService.get_blocks_batch: all {len(cids)} blocks local")
            return results

        local_hits = len(cids) - len(missing_cids)
        logger.debug(
            f"BlockService.get_blocks_batch: {local_hits} local hits, "
            f"{len(missing_cids)} fetching from network"
        )

        # Network pass for missing blocks
        network_results = await self.bitswap.get_blocks_batch(
            missing_cids, peer_id=peer_id, timeout=timeout, batch_size=batch_size
        )

        # Auto-cache all network-fetched blocks
        for cid_bytes, data in network_results.items():
            cid_obj = parse_cid(cid_bytes)
            await self.store.put_block(cid_obj, data)
            results[cid_bytes] = data

        return results

    @property
    def block_store(self) -> BlockStore:
        """Expose the underlying BlockStore (used by MerkleDag internals)."""
        return self.store
