"""
Regression tests for the `subscribed_mesh` fixture's predicate-based
readiness wait (#1307).

Covers that, after `subscribed_mesh` yields, every router's mesh for the
topic already contains the expected peers, so test bodies can rely on
mesh state without an additional sleep.
"""

from __future__ import annotations

import pytest

from tests.core.pubsub.conftest import subscribed_mesh

TOPIC = "test-mesh-ready"


@pytest.mark.trio
async def test_subscribed_mesh_yields_with_every_router_grafted() -> None:
    """Each router's mesh[topic] has at least min(n-1, degree_low) peers."""
    n = 3
    async with subscribed_mesh(TOPIC, n) as harness:
        for router in harness.routers:
            expected = min(n - 1, router.degree_low)
            assert len(router.mesh.get(TOPIC, set())) >= expected, (
                f"router mesh for {TOPIC!r} has "
                f"{len(router.mesh.get(TOPIC, set()))} peers, expected >= {expected}"
            )


def _flatten(exc: BaseException) -> list[BaseException]:
    """Recursively walk nested ExceptionGroups, returning the leaf exceptions."""
    if isinstance(exc, BaseExceptionGroup):
        out: list[BaseException] = []
        for child in exc.exceptions:
            out.extend(_flatten(child))
        return out
    return [exc]


@pytest.mark.trio
async def test_subscribed_mesh_rejects_unreachable_readiness() -> None:
    """A ready_timeout that's too short surfaces a TimeoutError, not a quiet sleep."""
    # Ask for an absurdly short timeout; the mesh can't form in 1ms.
    # Trio's background service managers nest ExceptionGroups, so flatten
    # the whole tree and confirm the TimeoutError is a leaf.
    with pytest.raises(BaseExceptionGroup) as exc_info:
        async with subscribed_mesh(TOPIC, 3, ready_timeout=0.001):
            pytest.fail("subscribed_mesh should have timed out before yielding")

    leaves = _flatten(exc_info.value)
    timeouts = [e for e in leaves if isinstance(e, TimeoutError)]
    assert timeouts, f"expected a TimeoutError leaf, got {leaves!r}"
    assert "mesh for topic" in str(timeouts[0])
