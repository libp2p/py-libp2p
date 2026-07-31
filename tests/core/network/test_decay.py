"""
Unit tests for the decaying tag subsystem (Phase 2).

Tests cover:
  - Preset decay and bump function factories
  - DecayingTag.bump() / remove() via Decayer
  - Decayer._tick() applying decay and erasing values
  - TagStore reflection after bump and tick
  - Resolution rounding behaviour
"""

from __future__ import annotations

import time

import pytest

from libp2p.network.decay import (
    Decayer,
    DecayingTag,
    bump_overwrite,
    bump_sum_bounded,
    bump_sum_unbounded,
    decay_expire_when_inactive,
    decay_fixed,
    decay_linear,
    decay_none,
)
from libp2p.network.tag_store import TagStore
from libp2p.peer.id import ID

PEER_A = ID.from_base58("QmcgpsyWgH8Y8ajJz1Cu72KnS5uo2Aa2LpzU7kinSupNKC")
PEER_B = ID.from_base58("QmTzQ1kKpJwVGgzJuEdq7wAA5EQUWbVcPKJ6M7eBz3vqv7")


# ── Preset decay function tests ────────────────────────────────────────────────


class TestDecayFunctions:
    """Test preset decay function factories."""

    def test_decay_none_preserves_value(self):
        """decay_none() always returns the same value and never erases."""
        fn = decay_none()
        for value in [0, 1, 50, 1000]:
            new_val, should_erase = fn(value)
            assert new_val == value
            assert should_erase is False

    def test_decay_fixed_subtracts(self):
        """decay_fixed(5) subtracts 5 each tick."""
        fn = decay_fixed(5)
        val, erase = fn(20)
        assert val == 15
        assert erase is False

    def test_decay_fixed_erases_at_zero(self):
        """decay_fixed erases when result hits 0."""
        fn = decay_fixed(10)
        val, erase = fn(10)
        assert val == 0
        assert erase is True

    def test_decay_fixed_erases_below_zero(self):
        """decay_fixed erases when result goes below 0."""
        fn = decay_fixed(15)
        val, erase = fn(10)
        assert val == -5
        assert erase is True

    def test_decay_linear_halves(self):
        """decay_linear(0.5) halves the value each tick."""
        fn = decay_linear(0.5)
        val, erase = fn(100)
        assert val == 50
        assert erase is False

    def test_decay_linear_erases_at_zero(self):
        """decay_linear erases when int(value * coef) == 0."""
        fn = decay_linear(0.5)
        val, erase = fn(1)  # int(1 * 0.5) == 0
        assert val == 0
        assert erase is True

    def test_decay_expire_when_inactive_is_noop(self):
        # decay_expire_when_inactive fn itself never erases
        # (Decayer checks last_bump).
        fn = decay_expire_when_inactive(60.0)
        val, erase = fn(100)
        assert val == 100
        assert erase is False

    def test_decay_expire_when_inactive_carries_threshold(self):
        """_after_seconds is stored on the function for Decayer to read."""
        fn = decay_expire_when_inactive(120.0)
        assert fn._after_seconds == 120.0  # type: ignore[attr-defined]


# ── Preset bump function tests ─────────────────────────────────────────────────


class TestBumpFunctions:
    """Test preset bump function factories."""

    def test_bump_overwrite_replaces(self):
        """bump_overwrite replaces old value with delta."""
        fn = bump_overwrite()
        assert fn(50, 10) == 10
        assert fn(0, 99) == 99

    def test_bump_sum_unbounded_adds(self):
        """bump_sum_unbounded adds delta without limit."""
        fn = bump_sum_unbounded()
        assert fn(50, 10) == 60
        assert fn(0, -5) == -5

    def test_bump_sum_bounded_clamps_max(self):
        """bump_sum_bounded clamps to max_val."""
        fn = bump_sum_bounded(0, 100)
        assert fn(90, 20) == 100

    def test_bump_sum_bounded_clamps_min(self):
        """bump_sum_bounded clamps to min_val."""
        fn = bump_sum_bounded(0, 100)
        assert fn(5, -10) == 0

    def test_bump_sum_bounded_stays_in_range(self):
        """bump_sum_bounded stays within bounds for normal inputs."""
        fn = bump_sum_bounded(0, 100)
        assert fn(50, 10) == 60


# ── Decayer unit tests ─────────────────────────────────────────────────────────


class TestDecayer:
    """Test Decayer registration, bump, remove, and _tick."""

    @pytest.fixture
    def store(self):
        return TagStore()

    @pytest.fixture
    def decayer(self, store):
        return Decayer(store, resolution=10.0)  # short resolution for tests

    def test_register_returns_decaying_tag(self, decayer):
        """register_decaying_tag returns a DecayingTag handle."""
        tag = decayer.register_decaying_tag(
            "score", 10.0, decay_none(), bump_sum_unbounded()
        )
        assert isinstance(tag, DecayingTag)
        assert tag.name == "score"

    def test_interval_rounds_up_to_resolution(self, decayer):
        """Intervals below resolution round up to resolution."""
        tag = decayer.register_decaying_tag(
            "fast", 5.0, decay_none(), bump_sum_unbounded()
        )
        assert tag.interval == 10.0  # rounded up from 5s to 10s (resolution)

    def test_interval_rounds_up_to_multiple(self, decayer):
        """Intervals above resolution round up to nearest multiple."""
        tag = decayer.register_decaying_tag(
            "medium", 25.0, decay_none(), bump_sum_unbounded()
        )
        assert tag.interval == 30.0  # ceil(25/10) * 10 == 30

    def test_bump_reflects_in_tagstore(self, decayer, store):
        """tag.bump() immediately updates TagStore value."""
        tag = decayer.register_decaying_tag(
            "score", 10.0, decay_none(), bump_sum_unbounded()
        )
        tag.bump(PEER_A, 10)
        assert store.get_tag(PEER_A, "score") == 10
        assert store.get_tag_value(PEER_A) == 10

    def test_bump_uses_bump_fn(self, decayer, store):
        """bump() applies the bump function, not raw assignment."""
        tag = decayer.register_decaying_tag(
            "capped", 10.0, decay_none(), bump_sum_bounded(0, 50)
        )
        tag.bump(PEER_A, 30)
        tag.bump(PEER_A, 30)  # 30 + 30 = 60 → clamped to 50
        assert store.get_tag(PEER_A, "capped") == 50

    def test_remove_untags_peer(self, decayer, store):
        """tag.remove() removes the tag from TagStore."""
        tag = decayer.register_decaying_tag(
            "score", 10.0, decay_none(), bump_sum_unbounded()
        )
        tag.bump(PEER_A, 20)
        tag.remove(PEER_A)
        assert store.get_tag(PEER_A, "score") == 0

    @pytest.mark.trio
    async def test_tick_applies_decay(self, decayer, store):
        """_tick() applies decay_fixed and updates TagStore."""
        tag = decayer.register_decaying_tag(
            "score", 10.0, decay_fixed(10), bump_sum_unbounded()
        )
        tag.bump(PEER_A, 100)
        await decayer._tick()
        assert store.get_tag(PEER_A, "score") == 90

    @pytest.mark.trio
    async def test_tick_erases_when_decayed_to_zero(self, decayer, store):
        """_tick() erases a tag when decay drops value to 0."""
        tag = decayer.register_decaying_tag(
            "score", 10.0, decay_fixed(100), bump_sum_unbounded()
        )
        tag.bump(PEER_A, 50)  # will decay: 50 - 100 = -50 → erase
        await decayer._tick()
        assert store.get_tag(PEER_A, "score") == 0
        assert (PEER_A, "score") not in decayer._values

    @pytest.mark.trio
    async def test_tick_erases_inactive(self, decayer, store):
        """_tick() erases tags inactive beyond after_seconds."""
        tag = decayer.register_decaying_tag(
            "recent", 10.0, decay_expire_when_inactive(0.0), bump_overwrite()
        )
        tag.bump(PEER_A, 99)
        # Force last_bump to be in the past
        key = (PEER_A, "recent")
        decayer._values[key].last_bump = time.time() - 100
        await decayer._tick()
        assert store.get_tag(PEER_A, "recent") == 0
        assert key not in decayer._values

    @pytest.mark.trio
    async def test_tick_multiple_peers(self, decayer, store):
        """_tick() correctly decays values for multiple peers independently."""
        tag = decayer.register_decaying_tag(
            "score", 10.0, decay_fixed(5), bump_sum_unbounded()
        )
        tag.bump(PEER_A, 20)
        tag.bump(PEER_B, 10)
        await decayer._tick()
        assert store.get_tag(PEER_A, "score") == 15
        # PEER_B: 10 - 5 = 5 (not erased)
        assert store.get_tag(PEER_B, "score") == 5

    @pytest.mark.trio
    async def test_second_bump_after_tick(self, decayer, store):
        """Bumping after a tick accumulates correctly."""
        tag = decayer.register_decaying_tag(
            "score", 10.0, decay_linear(0.5), bump_sum_unbounded()
        )
        tag.bump(PEER_A, 100)
        await decayer._tick()  # 100 → 50
        tag.bump(PEER_A, 20)  # 50 + 20 = 70
        assert store.get_tag(PEER_A, "score") == 70

    def test_multiple_tags_independent(self, decayer, store):
        """Multiple registered tags for the same peer are independent."""
        tag_a = decayer.register_decaying_tag(
            "a", 10.0, decay_none(), bump_sum_unbounded()
        )
        tag_b = decayer.register_decaying_tag(
            "b", 10.0, decay_none(), bump_sum_unbounded()
        )
        tag_a.bump(PEER_A, 10)
        tag_b.bump(PEER_A, 20)
        assert store.get_tag(PEER_A, "a") == 10
        assert store.get_tag(PEER_A, "b") == 20
        assert store.get_tag_value(PEER_A) == 30  # sum of both
