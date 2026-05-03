"""
Block storage interface for Bitswap.
"""

from abc import ABC, abstractmethod
from pathlib import Path

import trio

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


class FilesystemBlockStore(BlockStore):
    """
    Filesystem-based block store. Persists blocks to disk as files.

    Each block is stored as a file at:
        <base_path>/<first_2_chars_of_cid>/<rest_of_cid>

    This two-level directory structure avoids having too many files in a
    single directory and matches the layout used by py-ipfs-lite.

    Args:
        base_path: Root directory for block storage. Created if it doesn't exist.

    Example:
        >>> store = FilesystemBlockStore("/var/lib/myapp/blocks")
        >>> bitswap = BitswapClient(host, store)
        >>> # Blocks now survive process restarts!

        >>> # Drop-in replacement for MemoryBlockStore:
        >>> # store = MemoryBlockStore()       # before
        >>> store = FilesystemBlockStore("./blocks")  # after — persistent

    """

    def __init__(self, base_path: str | Path) -> None:
        """Initialize the filesystem block store."""
        self._path = Path(base_path)
        self._path.mkdir(parents=True, exist_ok=True)

    def _cid_to_path(self, cid: CIDInput) -> Path:
        """Convert a CID to a filesystem path using 2-char prefix directories."""
        cid_str = str(_normalize_cid(cid))
        # e.g. bafybeiabc... → <base>/ba/fybeiabc...
        return self._path / cid_str[:2] / cid_str[2:]

    async def get_block(self, cid: CIDInput) -> bytes | None:
        """Get a block by CID. Returns None if not found on disk."""
        path = self._cid_to_path(cid)
        if not path.exists():
            return None
        return await trio.to_thread.run_sync(path.read_bytes)

    async def put_block(self, cid: CIDInput, data: bytes) -> None:
        """Write a block to disk."""
        path = self._cid_to_path(cid)
        await trio.to_thread.run_sync(
            lambda: path.parent.mkdir(parents=True, exist_ok=True)
        )
        await trio.to_thread.run_sync(path.write_bytes, data)

    async def has_block(self, cid: CIDInput) -> bool:
        """Check if a block file exists on disk."""
        return self._cid_to_path(cid).exists()

    async def delete_block(self, cid: CIDInput) -> None:
        """Delete a block file from disk."""
        path = self._cid_to_path(cid)
        if path.exists():
            await trio.to_thread.run_sync(path.unlink)

    def get_all_cids(self) -> list[bytes]:
        """Return all stored CIDs as bytes by scanning the directory tree."""
        cids: list[bytes] = []
        if not self._path.exists():
            return cids
        for subdir in self._path.iterdir():
            if not subdir.is_dir():
                continue
            for entry in subdir.iterdir():
                if not entry.is_file():
                    continue
                cid_str = subdir.name + entry.name
                try:
                    cid_obj = _normalize_cid(cid_str)
                    cids.append(cid_obj.buffer)
                except Exception:
                    pass  # skip files that aren't valid CIDs
        return cids

    def size(self) -> int:
        """Return the number of stored blocks."""
        if not self._path.exists():
            return 0
        return sum(
            1
            for d in self._path.iterdir()
            if d.is_dir()
            for f in d.iterdir()
            if f.is_file()
        )

    def base_path(self) -> Path:
        """Return the root directory where blocks are stored."""
        return self._path
