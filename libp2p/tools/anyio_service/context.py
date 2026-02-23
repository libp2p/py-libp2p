"""Context managers and aliases for running services."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import anyio
import trio

if TYPE_CHECKING:
    from .api import ManagerAPI, ServiceAPI

from .manager import AnyIOManager
from .trio_manager import TrioManager

__all__ = [
    "background_trio_service",
    "background_anyio_service",
    "TrioManager",
    "AnyIOManager",
]


@asynccontextmanager
async def background_trio_service(service: ServiceAPI) -> AsyncIterator[ManagerAPI]:
    """
    Run a service in the background using Trio's structured concurrency.

    The service is running within the context block and will be properly
    cleaned up upon exiting the context block.

    Note: This uses TrioManager with pure Trio primitives for compatibility
    with existing Trio-based services (Swarm, PubSub, KadDHT, etc.).
    """
    async with trio.open_nursery() as nursery:
        manager = TrioManager(service)
        service._manager = manager

        nursery.start_soon(manager.run)
        await manager.wait_started()

        try:
            yield manager
        finally:
            await manager.stop()


@asynccontextmanager
async def background_anyio_service(service: ServiceAPI) -> AsyncIterator[ManagerAPI]:
    """
    Run a service in the background using AnyIO's structured concurrency.

    The service is running within the context block and will be properly
    cleaned up upon exiting the context block.

    This uses AnyIO and can work with either Trio or asyncio backends.
    """
    async with anyio.create_task_group() as tg:
        manager = AnyIOManager(service)
        service._manager = manager

        tg.start_soon(manager.run)  # type: ignore[arg-type]
        await manager.wait_started()

        try:
            yield manager
        finally:
            await manager.stop()


# ============================================================================
# No aliases needed - both managers are distinct
# ============================================================================
