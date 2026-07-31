"""
Decaying tag subsystem for py-libp2p connection manager.

Mirrors go-libp2p's core/connmgr Decayer interface:
https://pkg.go.dev/github.com/libp2p/go-libp2p/core/connmgr#Decayer

Decaying tags are like regular peer tags but their value automatically decreases
over time (each decay tick), and can only be raised via bump(). This makes them
useful for tracking transient peer value (e.g. recent successful requests) without
requiring manual cleanup — the value naturally falls to zero and is erased.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import math
import time
from typing import TYPE_CHECKING

import trio

if TYPE_CHECKING:
    from libp2p.network.tag_store import TagStore
    from libp2p.peer.id import ID

logger = logging.getLogger("libp2p.network.decay")

# ── Type aliases ───────────────────────────────────────────────────────────────

DecayFn = Callable[[int], tuple[int, bool]]
"""
Decay function type.

Called each tick with the current value.
Returns (new_value, should_erase):
  - new_value: the decayed value to store
  - should_erase: if True, the tag is removed entirely
"""

BumpFn = Callable[[int, int], int]
"""
Bump function type.

Called on bump() with (old_value, delta).
Returns the new value to store.
"""

DEFAULT_RESOLUTION = 60.0  # seconds — matches go-libp2p DefaultResolution


# ── Preset decay functions ─────────────────────────────────────────────────────


def decay_none() -> DecayFn:
    """
    Value never decays on its own; only bumps change it.

    Useful for tags that represent permanent state (e.g. protected peers).
    """
    return lambda value: (value, False)


def decay_fixed(minuend: int) -> DecayFn:
    """
    Subtract a fixed amount each tick; erase when value drops to or below 0.

    Parameters
    ----------
    minuend : int
        Amount to subtract each tick.

    """

    def fn(value: int) -> tuple[int, bool]:
        new_value = value - minuend
        return (new_value, new_value <= 0)

    return fn


def decay_linear(coef: float) -> DecayFn:
    """
    Multiply by coefficient each tick; erase when value hits 0.

    Parameters
    ----------
    coef : float
        Decay coefficient (e.g. 0.5 halves the value each tick).
        Must be in (0, 1] — values >= 1 never decay.

    """

    def fn(value: int) -> tuple[int, bool]:
        new_value = int(value * coef)
        return (new_value, new_value == 0)

    return fn


def decay_expire_when_inactive(after_seconds: float) -> DecayFn:
    """
    Erase the tag if it hasn't been bumped in ``after_seconds``.

    The Decayer checks DecayingValue.last_bump separately; this function
    itself is a no-op (it just carries the threshold as an attribute).

    Parameters
    ----------
    after_seconds : float
        Inactivity threshold in seconds.

    """

    def fn(value: int) -> tuple[int, bool]:
        return (value, False)  # Decayer checks last_bump separately

    fn._after_seconds = after_seconds  # type: ignore[attr-defined]
    return fn


# ── Preset bump functions ──────────────────────────────────────────────────────


def bump_overwrite() -> BumpFn:
    """Replace current value with the incoming delta."""
    return lambda _old, delta: delta


def bump_sum_unbounded() -> BumpFn:
    """Add delta to current value with no ceiling or floor."""
    return lambda old, delta: old + delta


def bump_sum_bounded(min_val: int, max_val: int) -> BumpFn:
    """
    Add delta, clamped to [min_val, max_val].

    Parameters
    ----------
    min_val : int
        Minimum allowed value.
    max_val : int
        Maximum allowed value.

    """
    return lambda old, delta: max(min_val, min(max_val, old + delta))


# ── Core types ─────────────────────────────────────────────────────────────────


@dataclass
class DecayingValue:
    """
    Internal state for a single (peer, tag) decaying value.

    Not part of the public API — managed entirely by Decayer.
    """

    tag_name: str
    peer_id: "ID"
    value: int = 0
    added_at: float = field(default_factory=time.time)
    last_bump: float = field(default_factory=time.time)


class DecayingTag:
    """
    Handle returned by Decayer.register_decaying_tag().

    The only way to move a decaying tag's value is bump() or let it decay —
    matching go-libp2p where values are never directly assigned.

    Thread-safety: bump() and remove() are synchronous and safe to call from
    any trio task (they don't await and the Decayer uses a plain dict).
    """

    def __init__(
        self,
        name: str,
        interval: float,
        decay_fn: DecayFn,
        bump_fn: BumpFn,
        decayer: "Decayer",
    ) -> None:
        self.name = name
        self.interval = interval
        self._decay_fn = decay_fn
        self._bump_fn = bump_fn
        self._decayer = decayer

    def bump(self, peer_id: "ID", delta: int) -> None:
        """
        Apply bump_fn to this peer's value for this tag.

        Parameters
        ----------
        peer_id : ID
            The peer to bump.
        delta : int
            The bump delta — interpreted by bump_fn (e.g. add, overwrite).

        """
        self._decayer.bump(peer_id, self, delta)

    def remove(self, peer_id: "ID") -> None:
        """
        Remove this decaying tag from a peer entirely.

        Parameters
        ----------
        peer_id : ID
            The peer to remove the tag from.

        """
        self._decayer.remove(peer_id, self)


class Decayer:
    """
    Owns all registered decaying tags and runs the periodic decay tick.

    Lifecycle
    ---------
    Start: call ``run_background_task(nursery)`` from Swarm.run().
    Stop: the trio nursery cancellation propagates naturally; or call stop().

    The Decayer ticks every ``resolution`` seconds and applies each registered
    tag's decay function to all peers that have a non-zero value for that tag.
    Values that hit zero (or where should_erase is True) are removed from the
    TagStore and from the Decayer's internal state.
    """

    def __init__(
        self,
        tag_store: "TagStore",
        resolution: float = DEFAULT_RESOLUTION,
    ) -> None:
        """
        Initialise the Decayer.

        Parameters
        ----------
        tag_store : TagStore
            The tag store to update when bumping or decaying.
        resolution : float
            Clock tick interval in seconds.  Individual tag intervals are
            rounded up to the nearest multiple of this value.

        """
        self._tag_store = tag_store
        self._resolution = resolution
        self._tags: dict[str, DecayingTag] = {}
        # (peer_id, tag_name) → DecayingValue
        self._values: dict[tuple["ID", str], DecayingValue] = {}
        self._started = False
        self._cancel_scope: trio.CancelScope | None = None

    def register_decaying_tag(
        self,
        name: str,
        interval: float,
        decay_fn: DecayFn,
        bump_fn: BumpFn,
    ) -> DecayingTag:
        """
        Register a new decaying tag and return its handle.

        The tag interval is rounded up to the next resolution multiple,
        matching go-libp2p's ``BasicConnMgr`` behaviour.

        Parameters
        ----------
        name : str
            Unique tag name (must not clash with plain tag names in TagStore).
        interval : float
            Target decay tick interval in seconds.
        decay_fn : DecayFn
            Called each tick with the current value.
        bump_fn : BumpFn
            Called on bump() with (old_value, delta).

        Returns
        -------
        DecayingTag
            Handle for bumping and removing this tag.

        """
        if interval < self._resolution:
            effective_interval = self._resolution
        else:
            effective_interval = (
                math.ceil(interval / self._resolution) * self._resolution
            )
        tag = DecayingTag(name, effective_interval, decay_fn, bump_fn, self)
        self._tags[name] = tag
        return tag

    def bump(self, peer_id: "ID", tag: "DecayingTag", delta: int) -> None:
        """
        Apply bump_fn synchronously and reflect in TagStore immediately.

        Called from DecayingTag.bump() — no await needed.

        Parameters
        ----------
        peer_id : ID
            Target peer.
        tag : DecayingTag
            Tag whose bump_fn will be applied.
        delta : int
            Bump delta, passed to bump_fn.

        """
        key = (peer_id, tag.name)
        dv = self._values.get(key)
        if dv is None:
            dv = DecayingValue(tag_name=tag.name, peer_id=peer_id)
            self._values[key] = dv
        old_value = dv.value
        new_value = tag._bump_fn(dv.value, delta)
        dv.value = new_value
        dv.last_bump = time.time()
        # Mirror into TagStore so sort_connections sees the updated value.
        captured = new_value
        self._tag_store.upsert_tag(peer_id, tag.name, lambda _: captured)
        logger.debug(
            "Bumped decaying tag %r for peer %s: %d → %d",
            tag.name, peer_id, old_value, new_value,
        )

    def remove(self, peer_id: "ID", tag: "DecayingTag") -> None:
        """
        Remove a decaying tag from a peer.

        Called from DecayingTag.remove() — no await needed.

        Parameters
        ----------
        peer_id : ID
            Target peer.
        tag : DecayingTag
            Tag to remove.

        """
        key = (peer_id, tag.name)
        if self._values.pop(key, None) is not None:
            self._tag_store.untag_peer(peer_id, tag.name)

    async def run_background_task(self, nursery: trio.Nursery) -> None:
        """
        Schedule the decay ticker as a background trio task.

        Called from Swarm.run() alongside ConnectionPruner and AutoConnector.

        Parameters
        ----------
        nursery : trio.Nursery
            The nursery to start the decay loop in.

        """
        nursery.start_soon(self._decay_loop)

    async def _decay_loop(self) -> None:
        """Main decay loop — ticks every ``_resolution`` seconds."""
        self._started = True
        try:
            with trio.CancelScope() as scope:
                self._cancel_scope = scope
                while True:
                    await trio.sleep(self._resolution)
                    await self._tick()
        finally:
            self._started = False
            self._cancel_scope = None

    async def _tick(self) -> None:
        """
        Apply all registered decay functions to all tracked (peer, tag) values.

        Erased entries are removed from both the Decayer's internal state and
        the TagStore so the next connection prune cycle sees up-to-date values.
        """
        to_erase: list[tuple["ID", str]] = []

        for (peer_id, tag_name), dv in list(self._values.items()):
            tag = self._tags.get(tag_name)
            if tag is None:
                # Tag was unregistered while values existed — clean up.
                to_erase.append((peer_id, tag_name))
                continue

            # Handle decay_expire_when_inactive: check last_bump staleness.
            after_seconds = getattr(tag._decay_fn, "_after_seconds", None)
            if after_seconds is not None:
                if (time.time() - dv.last_bump) > after_seconds:
                    to_erase.append((peer_id, tag_name))
                    continue

            new_value, should_erase = tag._decay_fn(dv.value)
            if should_erase or new_value <= 0:
                to_erase.append((peer_id, tag_name))
            else:
                dv.value = new_value
                captured = new_value
                self._tag_store.upsert_tag(peer_id, tag_name, lambda _: captured)

        for peer_id, tag_name in to_erase:
            self._values.pop((peer_id, tag_name), None)
            self._tag_store.untag_peer(peer_id, tag_name)
            logger.debug("Erased decaying tag %r for peer %s", tag_name, peer_id)

    async def stop(self) -> None:
        """Cancel the decay loop (idempotent)."""
        if self._cancel_scope is not None:
            self._cancel_scope.cancel()
