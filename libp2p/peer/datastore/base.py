"""
Base datastore interface for persistent peer storage.

This module defines the abstract interface that all datastore implementations
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator


class IDatastore(ABC):
    """
    Abstract interface for datastore operations.

    This interface is inspired by the go-datastore interface and provides
    the core operations needed for persistent peer storage.
    """

    @abstractmethod
    async def get(self, key: bytes) -> bytes | None:
        """
        Retrieve a value by key.

        Args:
            key: The key to look up

        Returns:
            The value if found, None otherwise

        Raises:
            KeyError: If the key is not found

        """
        pass

    @abstractmethod
    async def put(self, key: bytes, value: bytes) -> None:
        """
        Store a key-value pair.

        Args:
            key: The key to store
            value: The value to store

        """
        pass

    @abstractmethod
    async def delete(self, key: bytes) -> None:
        """
        Delete a key-value pair.

        Args:
            key: The key to delete

        """
        pass

    @abstractmethod
    async def has(self, key: bytes) -> bool:
        """
        Check if a key exists.

        Args:
            key: The key to check

        Returns:
            True if the key exists, False otherwise

        """
        pass

    @abstractmethod
    def query(self, prefix: bytes) -> Iterator[tuple[bytes, bytes]]:
        """
        Query for keys with a given prefix.

        Args:
            prefix: The key prefix to search for

        Yields:
            Tuples of (key, value) for matching entries

        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """
        Close the datastore and clean up resources.
        """
        pass

    @abstractmethod
    async def sync(self, prefix: bytes) -> None:
        """
        Sync any pending writes to disk.

        Args:
            prefix: The key prefix to sync (empty bytes for all keys)

        """
        pass


class IBatchingDatastore(IDatastore):
    """
    Extended datastore interface that supports batched operations.

    This is useful for performance optimization when making multiple
    write operations.
    """

    @abstractmethod
    async def batch(self) -> "IBatch":
        """
        Create a new batch for batched operations.

        Returns:
            A batch object for performing multiple operations atomically

        """
        pass


class IBatch(ABC):
    """
    Interface for batched datastore operations.
    """

    @abstractmethod
    async def put(self, key: bytes, value: bytes) -> None:
        """
        Add a put operation to the batch.

        Args:
            key: The key to store
            value: The value to store

        """
        pass

    @abstractmethod
    async def delete(self, key: bytes) -> None:
        """
        Add a delete operation to the batch.

        Args:
            key: The key to delete

        """
        pass

    @abstractmethod
    async def commit(self) -> None:
        """
        Commit all operations in the batch atomically.
        """
        pass
