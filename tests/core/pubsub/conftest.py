"""Shared fixtures and helpers for pubsub tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import dataclasses
from typing import Any

import pytest
import trio

from libp2p.abc import IHost
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from tests.utils.factories import PubsubFactory
from tests.utils.pubsub.utils import dense_connect


@dataclasses.dataclass(frozen=True, slots=True)
class GossipSubHarness:
    """Typed wrapper around a batch of GossipSub-backed pubsub instances."""

    pubsubs: tuple[Pubsub, ...]

    @property
    def hosts(self) -> tuple[IHost, ...]:
        return tuple(ps.host for ps in self.pubsubs)

    @property
    def routers(self) -> tuple[GossipSub, ...]:
        result: list[GossipSub] = []
        for ps in self.pubsubs:
            r = ps.router
            assert isinstance(r, GossipSub), f"Expected GossipSub, got {type(r)}"
            result.append(r)
        return tuple(result)

    def __len__(self) -> int:
        return len(self.pubsubs)


@asynccontextmanager
async def gossipsub_nodes(n: int, **kwargs: Any) -> AsyncIterator[GossipSubHarness]:
    """
    Create *n* GossipSub-backed pubsub nodes wrapped in a harness.

    Usage::

        async with gossipsub_nodes(3, heartbeat_interval=0.5) as h:
            h.pubsubs   # tuple[Pubsub, ...]
            h.hosts      # tuple[IHost, ...]
            h.routers    # tuple[GossipSub, ...]
    """
    async with PubsubFactory.create_batch_with_gossipsub(n, **kwargs) as pubsubs:
        yield GossipSubHarness(pubsubs=pubsubs)


@asynccontextmanager
async def connected_gossipsub_nodes(
    n: int, **kwargs: Any
) -> AsyncIterator[GossipSubHarness]:
    """Create *n* GossipSub nodes with dense connectivity."""
    async with gossipsub_nodes(n, **kwargs) as harness:
        await dense_connect(harness.hosts)
        await trio.sleep(0.1)
        yield harness


@asynccontextmanager
async def subscribed_mesh(
    topic: str, n: int, *, settle_time: float = 1.0, **kwargs: Any
) -> AsyncIterator[GossipSubHarness]:
    """
    Create *n* connected GossipSub nodes all subscribed to *topic*.

    Waits *settle_time* seconds for mesh formation before yielding.
    """
    async with connected_gossipsub_nodes(n, **kwargs) as harness:
        for ps in harness.pubsubs:
            await ps.subscribe(topic)
        await trio.sleep(settle_time)
        yield harness


@pytest.fixture
async def connected_gossipsub_pair() -> AsyncIterator[GossipSubHarness]:
    """Fixture: two connected GossipSub nodes with default config."""
    async with connected_gossipsub_nodes(2) as harness:
        yield harness
