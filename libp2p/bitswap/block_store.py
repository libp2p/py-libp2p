"""
Block storage interface for Bitswap.
"""

from abc import ABC, abstractmethod

from .cid import CIDInput, CIDObject, parse_cid


def _normalize_cid(cid: CIDInput) -> CIDObject:
    """Normalize accepted CID input forms to a py-cid object."""
    return parse_cid(cid)


class BlockStore(ABC):
    """
    Abstract interface for storing and retrieving blocks.

    Implementations should provide persistent or in-memory storage
    for content-addressed blocks.
    """

    @abstractmethod
    async def get_block(self, cid: CIDInput) -> bytes | None:
        """
        Get a block by its CID.

        Args:
            cid: The CID of the block to retrieve

        Returns:
            The block data if found, None otherwise

        """
        pass

    @abstractmethod
    async def put_block(self, cid: CIDInput, data: bytes) -> None:
        """
        Store a block.

        Args:
            cid: The CID of the block
            data: The block data

        """
        pass

    @abstractmethod
    async def has_block(self, cid: CIDInput) -> bool:
        """
        Check if a block exists.

        Args:
            cid: The CID of the block

        Returns:
            True if the block exists, False otherwise

        """
        pass

    @abstractmethod
    async def delete_block(self, cid: CIDInput) -> None:
        """
        Delete a block.

        Args:
            cid: The CID of the block to delete

        """
        pass

    @abstractmethod
    def get_all_cids(self) -> list[bytes]:
        """
        Get all CIDs in the block store.

        Returns:
            List of all CIDs as bytes

        """
        pass


class MemoryBlockStore(BlockStore):
    """In-memory block store implementation using CID objects as keys."""

    def __init__(self) -> None:
        """Initialize the memory block store."""
        self._blocks: dict[CIDObject, bytes] = {}

    async def get_block(self, cid: CIDInput) -> bytes | None:
        """Get a block by its CID."""
        cid_obj = _normalize_cid(cid)
        return self._blocks.get(cid_obj)

    async def put_block(self, cid: CIDInput, data: bytes) -> None:
        """Store a block."""
        cid_obj = _normalize_cid(cid)
        self._blocks[cid_obj] = data

    async def has_block(self, cid: CIDInput) -> bool:
        """Check if a block exists."""
        cid_obj = _normalize_cid(cid)
        return cid_obj in self._blocks

    async def delete_block(self, cid: CIDInput) -> None:
        """Delete a block."""
        cid_obj = _normalize_cid(cid)
        if cid_obj in self._blocks:
            del self._blocks[cid_obj]

    def get_all_cids(self) -> list[bytes]:
        """Get all CIDs in the store as bytes (for caller compatibility)."""
        return [cid_obj.buffer for cid_obj in self._blocks]

    def size(self) -> int:
        """Get the number of blocks in the store."""
        return len(self._blocks)
