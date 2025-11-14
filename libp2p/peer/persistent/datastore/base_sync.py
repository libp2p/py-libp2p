"""
Synchronous datastore interfaces for persistent peer storage.

This module defines the synchronous interfaces that all sync datastore
implementations must follow, providing the core operations needed for
persistent peer storage without async/await.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator


class IDatastoreSync(ABC):
    """
    Abstract interface for synchronous datastore operations.

    This interface provides synchronous equivalents of the async datastore
    operations, allowing for pure synchronous peerstore implementations.
    """

    @abstractmethod
    def get(self, key: bytes) -> bytes | None:
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
    def put(self, key: bytes, value: bytes) -> None:
        """
        Store a key-value pair.

        Args:
            key: The key to store
            value: The value to store

        """
        pass

    @abstractmethod
    def delete(self, key: bytes) -> None:
        """
        Delete a key-value pair.

        Args:
            key: The key to delete

        """
        pass

    @abstractmethod
    def has(self, key: bytes) -> bool:
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
    def close(self) -> None:
        """
        Close the datastore and clean up resources.
        """
        pass

    @abstractmethod
    def sync(self, prefix: bytes) -> None:
        """
        Sync any pending writes to disk.

        Args:
            prefix: The key prefix to sync (empty bytes for all keys)

        """
        pass


class IBatchingDatastoreSync(IDatastoreSync):
    """
    Extended synchronous datastore interface that supports batched operations.

    This is useful for performance optimization when making multiple
    write operations.
    """

    @abstractmethod
    def batch(self) -> "IBatchSync":
        """
        Create a new batch for batched operations.

        Returns:
            A batch object for performing multiple operations atomically

        """
        pass


class IBatchSync(ABC):
    """
    Interface for synchronous batched datastore operations.
    """

    @abstractmethod
    def put(self, key: bytes, value: bytes) -> None:
        """
        Add a put operation to the batch.

        Args:
            key: The key to store
            value: The value to store

        """
        pass

    @abstractmethod
    def delete(self, key: bytes) -> None:
        """
        Add a delete operation to the batch.

        Args:
            key: The key to delete

        """
        pass

    @abstractmethod
    def commit(self) -> None:
        """
        Commit all operations in the batch atomically.
        """
        pass
