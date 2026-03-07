"""Early data handlers for Noise protocol."""

from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Awaitable, Callable
from typing import (
    Protocol,
    runtime_checkable,
)


@runtime_checkable
class EarlyDataHandler(Protocol):
    """Protocol for handling early data in Noise handshake."""

    async def handle_early_data(self, data: bytes) -> None:
        """
        Handle early data received during handshake.

        Args:
            data: The early data received

        Raises:
            Exception: If early data cannot be processed

        """
        ...


class AsyncEarlyDataHandler(ABC):
    """Abstract base class for async early data handlers."""

    @abstractmethod
    async def handle_early_data(self, data: bytes) -> None:
        """
        Handle early data received during handshake.

        Args:
            data: The early data received

        Raises:
            Exception: If early data cannot be processed

        """
        pass


class SyncEarlyDataHandler(ABC):
    """Abstract base class for synchronous early data handlers."""

    @abstractmethod
    def handle_early_data(self, data: bytes) -> None:
        """
        Handle early data received during handshake.

        Args:
            data: The early data received

        Raises:
            Exception: If early data cannot be processed

        """
        pass


class LoggingEarlyDataHandler(AsyncEarlyDataHandler):
    """Early data handler that logs received data."""

    def __init__(self, logger_name: str = "early_data"):
        self.logger_name = logger_name

    async def handle_early_data(self, data: bytes) -> None:
        """
        Log the received early data.

        Args:
            data: The early data received

        """
        import logging

        logger = logging.getLogger(self.logger_name)
        logger.info(f"Received early data: {len(data)} bytes")
        logger.debug(f"Early data content: {data!r}")


class BufferingEarlyDataHandler(AsyncEarlyDataHandler):
    """Early data handler that buffers received data."""

    def __init__(self, max_buffer_size: int = 1024 * 1024):  # 1MB default
        self.max_buffer_size = max_buffer_size
        self.buffer: list[bytes] = []
        self.total_size = 0

    async def handle_early_data(self, data: bytes) -> None:
        """
        Buffer the received early data.

        Args:
            data: The early data received

        Raises:
            ValueError: If buffer size would exceed maximum

        """
        if self.total_size + len(data) > self.max_buffer_size:
            raise ValueError(
                f"Early data buffer size would exceed maximum of "
                f"{self.max_buffer_size} bytes"
            )

        self.buffer.append(data)
        self.total_size += len(data)

    def get_buffered_data(self) -> bytes:
        """
        Get all buffered early data.

        Returns:
            bytes: All buffered early data concatenated

        """
        return b"".join(self.buffer)

    def clear_buffer(self) -> None:
        """Clear the early data buffer."""
        self.buffer.clear()
        self.total_size = 0

    def __len__(self) -> int:
        """Get the number of buffered data chunks."""
        return len(self.buffer)

    @property
    def size(self) -> int:
        """Get the total size of buffered data."""
        return self.total_size


class CallbackEarlyDataHandler(AsyncEarlyDataHandler):
    """Early data handler that calls a user-provided callback."""

    def __init__(
        self, callback: Callable[[bytes], None] | Callable[[bytes], Awaitable[None]]
    ) -> None:
        """
        Initialize with a callback function.

        Args:
            callback: Function to call with early data

        """
        self.callback = callback

    async def handle_early_data(self, data: bytes) -> None:
        """
        Call the user-provided callback with early data.

        Args:
            data: The early data received

        Raises:
            Exception: If the callback raises an exception

        """
        # Try to call as async, fall back to sync if needed
        result = self.callback(data)
        if hasattr(result, "__await__"):
            await result  # type: ignore


class CompositeEarlyDataHandler(AsyncEarlyDataHandler):
    """Early data handler that delegates to multiple handlers."""

    def __init__(self, handlers: list[EarlyDataHandler]):
        """
        Initialize with a list of handlers.

        Args:
            handlers: List of early data handlers

        """
        self.handlers = handlers

    async def handle_early_data(self, data: bytes) -> None:
        """
        Handle early data by delegating to all handlers.

        Args:
            data: The early data received

        Raises:
            Exception: If any handler raises an exception

        """
        for handler in self.handlers:
            # Try to call as async, fall back to sync if needed
            try:
                await handler.handle_early_data(data)
            except TypeError:
                # Handler is sync, call directly
                await handler.handle_early_data(data)

    def add_handler(self, handler: EarlyDataHandler) -> None:
        """
        Add a handler to the composite.

        Args:
            handler: Early data handler to add

        """
        self.handlers.append(handler)

    def remove_handler(self, handler: EarlyDataHandler) -> None:
        """
        Remove a handler from the composite.

        Args:
            handler: Early data handler to remove

        """
        if handler in self.handlers:
            self.handlers.remove(handler)


class EarlyDataManager:
    """Manager for early data handling in Noise protocol."""

    def __init__(self, handler: EarlyDataHandler | None = None):
        """
        Initialize with an optional early data handler.

        Args:
            handler: Early data handler to use

        """
        self.handler = handler
        self._early_data_received = False
        self._early_data_buffer: bytes | None = None

    async def handle_early_data(self, data: bytes) -> None:
        """
        Handle early data using the configured handler.

        Args:
            data: The early data received

        """
        self._early_data_received = True
        self._early_data_buffer = data

        if self.handler is not None:
            # Try to call as async, fall back to sync if needed
            try:
                await self.handler.handle_early_data(data)
            except TypeError:
                # Handler is sync, call directly
                await self.handler.handle_early_data(data)

    def has_early_data(self) -> bool:
        """
        Check if early data has been received.

        Returns:
            bool: True if early data has been received

        """
        return self._early_data_received

    def get_early_data(self) -> bytes | None:
        """
        Get the received early data.

        Returns:
            Optional[bytes]: The early data if received, None otherwise

        """
        return self._early_data_buffer

    def clear_early_data(self) -> None:
        """Clear the early data buffer."""
        self._early_data_received = False
        self._early_data_buffer = None

    def set_handler(self, handler: EarlyDataHandler) -> None:
        """
        Set a new early data handler.

        Args:
            handler: Early data handler to use

        """
        self.handler = handler
