"""
Regression tests for the `subscribed_mesh` fixture's predicate-based
readiness wait (#1307).

Covers that, after `subscribed_mesh` yields, every router's mesh for the
topic already contains the expected peers, so test bodies can rely on
mesh state without an additional sleep.
"""

from __future__ import annotations

import sys

import pytest

# Python 3.10 doesn't have BaseExceptionGroup as a builtin; fall back to the
# exceptiongroup backport the rest of this repo already depends on.
if sys.version_info < (3, 11):  # pragma: no cover
    from exceptiongroup import BaseExceptionGroup  # type: ignore[assignment]

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
    """
    Unreachable readiness surfaces a TimeoutError, not a quiet yield.

    Uses an unsatisfiable readiness predicate so the timeout path is exercised
    deterministically — relying on a tiny ``ready_timeout`` is racy, since the
    mesh may already be formed by the first poll (``wait_for`` checks the
    predicate before the deadline), in which case the fixture yields instead.
    Trio may or may not wrap the TimeoutError in an ExceptionGroup depending on
    nursery strictness, so catch broadly and assert on the flattened leaves.
    """
    raised: BaseException | None = None
    try:
        async with subscribed_mesh(
            TOPIC, 3, ready_predicate=lambda: False, ready_timeout=0.05
        ):
            pytest.fail("subscribed_mesh should have timed out before yielding")
    except BaseException as exc:
        raised = exc

    assert raised is not None, "expected subscribed_mesh to raise"
    leaves = _flatten(raised)
    timeouts = [e for e in leaves if isinstance(e, TimeoutError)]
    assert timeouts, f"expected a TimeoutError leaf, got {leaves!r}"
    assert "mesh for topic" in str(timeouts[0])


@pytest.mark.trio
async def test_subscribed_mesh_rejects_non_positive_timing() -> None:
    """ready_timeout and poll_interval must be strictly positive."""
    for bad in (0, -0.5):
        with pytest.raises(ValueError, match="ready_timeout"):
            async with subscribed_mesh(TOPIC, 2, ready_timeout=bad):
                pytest.fail("validation should have rejected the argument")
        with pytest.raises(ValueError, match="poll_interval"):
            async with subscribed_mesh(TOPIC, 2, poll_interval=bad):
                pytest.fail("validation should have rejected the argument")
