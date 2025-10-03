"""Context managers and aliases for running services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import trio

if TYPE_CHECKING:
    from .api import ManagerAPI, ServiceAPI

from .manager import AnyIOManager

__all__ = ["background_trio_service", "TrioManager"]


@asynccontextmanager
async def background_trio_service(service: ServiceAPI) -> AsyncIterator[ManagerAPI]:
    """
    Run a service in the background using Trio's structured concurrency.

    The service is running within the context block and will be properly
    cleaned up upon exiting the context block.

    Args:
        service: A :class:`~libp2p.tools.anyio_service.api.ServiceAPI` instance to run.

    Yields:
        A :class:`~libp2p.tools.anyio_service.api.ManagerAPI` instance.

    """
    async with trio.open_nursery() as nursery:
        manager = AnyIOManager(service)
        service._manager = manager

        nursery.start_soon(manager.run)
        await manager.wait_started()

        try:
            yield manager
        finally:
            await manager.stop()


# ============================================================================
# Compatibility Alias for Trio
# ============================================================================

TrioManager = AnyIOManager  # Alias for backward compatibility
