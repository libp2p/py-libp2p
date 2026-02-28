"""
Block storage interface for Bitswap.
"""

from abc import ABC, abstractmethod

from .cid import CIDInput, cid_to_bytes


def _normalize_cid(cid: CIDInput) -> bytes:
    """Normalize accepted CID input forms to canonical CID bytes."""
    return cid_to_bytes(cid)


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
            List of all CIDs

        """
        pass


class MemoryBlockStore(BlockStore):
    """In-memory block store implementation."""

    def __init__(self) -> None:
        """Initialize the memory block store."""
        self._blocks: dict[bytes, bytes] = {}

    async def get_block(self, cid: CIDInput) -> bytes | None:
        """Get a block by its CID."""
        cid_bytes = _normalize_cid(cid)
        return self._blocks.get(cid_bytes)

    async def put_block(self, cid: CIDInput, data: bytes) -> None:
        """Store a block."""
        cid_bytes = _normalize_cid(cid)
        self._blocks[cid_bytes] = data

    async def has_block(self, cid: CIDInput) -> bool:
        """Check if a block exists."""
        cid_bytes = _normalize_cid(cid)
        return cid_bytes in self._blocks

    async def delete_block(self, cid: CIDInput) -> None:
        """Delete a block."""
        cid_bytes = _normalize_cid(cid)
        if cid_bytes in self._blocks:
            del self._blocks[cid_bytes]

    def get_all_cids(self) -> list[bytes]:
        """Get all CIDs in the store."""
        return list(self._blocks.keys())

    def size(self) -> int:
        """Get the number of blocks in the store."""
        return len(self._blocks)
