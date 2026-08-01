"""Shared fixtures and helpers for pubsub tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
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
from tests.utils.pubsub.wait import wait_for


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
    n: int, *, strict: bool = False, **kwargs: Any
) -> AsyncIterator[GossipSubHarness]:
    """
    Create *n* GossipSub nodes with dense connectivity.

    By default this waits only until each node has observed one expected
    neighbour (fast path). Pass ``strict=True`` to wait until every node
    has observed every other expected peer — useful for topology-sensitive
    tests that assert exact peer counts or full fanout behaviour.
    """
    peer_wait_timeout = kwargs.pop("peer_wait_timeout", 5.0)
    async with gossipsub_nodes(n, **kwargs) as harness:
        await dense_connect(harness.hosts)
        if n > 1:
            with trio.fail_after(peer_wait_timeout):
                if strict:
                    for index, pubsub in enumerate(harness.pubsubs):
                        for other_index, other_host in enumerate(harness.hosts):
                            if other_index == index:
                                continue
                            await pubsub.wait_for_peer(other_host.get_id())
                else:
                    for index, pubsub in enumerate(harness.pubsubs):
                        target_host = harness.hosts[(index + 1) % n]
                        await pubsub.wait_for_peer(target_host.get_id())
        yield harness


@asynccontextmanager
async def subscribed_mesh(
    topic: str,
    n: int,
    *,
    ready_timeout: float = 5.0,
    poll_interval: float = 0.02,
    ready_predicate: Callable[[], bool] | None = None,
    **kwargs: Any,
) -> AsyncIterator[GossipSubHarness]:
    """
    Create *n* connected GossipSub nodes all subscribed to *topic*.

    Waits (up to *ready_timeout* seconds) for every router's mesh for
    *topic* to contain at least ``min(n - 1, router.degree_low)`` peers
    before yielding. This replaces the previous fixed-sleep wait with a
    deterministic, predicate-driven poll (see #1307).

    *ready_predicate* overrides the default mesh-readiness check; pass an
    unsatisfiable predicate to exercise the timeout path deterministically
    (the default cannot be made to time out reliably, since the mesh may
    already be formed by the first poll).
    """
    if ready_timeout <= 0:
        raise ValueError(f"ready_timeout must be > 0, got {ready_timeout!r}")
    if poll_interval <= 0:
        raise ValueError(f"poll_interval must be > 0, got {poll_interval!r}")

    async with connected_gossipsub_nodes(n, **kwargs) as harness:
        for ps in harness.pubsubs:
            await ps.subscribe(topic)

        routers = harness.routers

        def _mesh_ready() -> bool:
            for router in routers:
                expected = min(n - 1, router.degree_low)
                if len(router.mesh.get(topic, set())) < expected:
                    return False
            return True

        await wait_for(
            ready_predicate or _mesh_ready,
            timeout=ready_timeout,
            poll_interval=poll_interval,
            fail_msg=(
                f"mesh for topic {topic!r} did not form on all {n} routers "
                f"within {ready_timeout}s"
            ),
        )
        yield harness


@pytest.fixture
async def connected_gossipsub_pair() -> AsyncIterator[GossipSubHarness]:
    """Fixture: two connected GossipSub nodes with default config."""
    async with connected_gossipsub_nodes(2) as harness:
        yield harness
