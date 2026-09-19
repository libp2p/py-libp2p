"""
KEM helpers for the Noise XXhfs handshake.

``make_fast_kem()`` returns the default KEM for the suite, and ``KeypairPool``
pre-computes keypairs so a handshake does not pay ML-KEM keygen inline.

The default backend is the native one, ``MLKEM768NativeKem``, built on
``cryptography``'s ML-KEM. kyber-py (pure Python) is the fallback when the
native backend is unavailable: see the note on ``make_fast_kem``.
"""

from __future__ import annotations

import asyncio
from collections import deque
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .kem import IKem

logger = logging.getLogger(__name__)

_ML_KEM_768_PK_SIZE = 1184
_ML_KEM_768_CT_SIZE = 1088
_X25519_KEY_SIZE = 32


def make_fast_kem() -> IKem:
    """
    Return the fastest available ML-KEM-768 KEM backend.

    Prefers :class:`~libp2p.security.noise.pq.kem.MLKEM768NativeKem`, which
    uses ``cryptography``'s native ML-KEM. Falls back to the pure-Python
    :class:`~libp2p.security.noise.pq.kem.MLKEM768Kem` (kyber-py) when the
    native one is unavailable, which happens when ``cryptography`` predates
    48.0.0 or was built without ML-KEM support. The two backends interoperate
    on the wire, so the choice is local to each peer.
    """
    from .kem import MLKEM768Kem, MLKEM768NativeKem

    try:
        return MLKEM768NativeKem()
    except ImportError as exc:
        logger.debug("native ML-KEM-768 backend unavailable, using kyber-py: %s", exc)
        return MLKEM768Kem()


class KeypairPool:
    """
    Pre-computes KEM keypairs during idle time to eliminate keygen latency
    on the connection critical path.

    With kyber-py, keygen costs ~20 ms. A pool of 3 pre-generated keypairs
    means 3 handshakes can proceed without paying any keygen cost. Background
    refill uses asyncio.to_thread() so the event loop is not blocked.

    Usage:
        pool = await KeypairPool.create(kem, min_size=3)
        pk, sk = pool.acquire()   # instant

    Note: The pool is not thread-safe. All calls must be made from the same
    event loop thread (which is the norm for asyncio Python code).
    """

    def __init__(self, kem: IKem, min_size: int = 3) -> None:
        self._kem = kem
        self._min_size = min_size
        self._pool: deque[tuple[bytes, bytes]] = deque()
        self._refill_task: asyncio.Task[None] | None = None

    @classmethod
    async def create(cls, kem: IKem, min_size: int = 3) -> KeypairPool:
        """
        Create a pool and fill it with pre-generated keypairs.

        Uses asyncio.to_thread() for the blocking keygen calls so the event
        loop stays responsive during construction.
        """
        pool = cls(kem, min_size)
        await pool._async_fill()
        return pool

    def acquire(self) -> tuple[bytes, bytes]:
        """
        Return a pre-generated keypair. If the pool is empty, generates
        one synchronously (a fallback that should not happen in normal operation).
        Schedules an async refill if the pool drops below min_size.
        """
        if self._pool:
            kp = self._pool.popleft()
        else:
            logger.warning("KeypairPool exhausted; generating synchronously")
            kp = self._kem.keygen()

        if len(self._pool) < self._min_size and self._refill_task is None:
            self._schedule_refill()
        return kp

    @property
    def size(self) -> int:
        return len(self._pool)

    def _schedule_refill(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop, so skip background refill
        self._refill_task = loop.create_task(self._async_fill())
        self._refill_task.add_done_callback(self._on_refill_done)

    def _on_refill_done(self, task: asyncio.Task[None]) -> None:
        self._refill_task = None
        if task.cancelled():
            return  # event loop shutting down, which is normal
        exc = task.exception()
        if exc:
            logger.error("KeypairPool refill failed: %s", exc)

    async def _async_fill(self) -> None:
        needed = self._min_size - len(self._pool)
        if needed <= 0:
            return
        loop = asyncio.get_running_loop()
        keypairs = await asyncio.gather(
            *(loop.run_in_executor(None, self._kem.keygen) for _ in range(needed))  # type: ignore[arg-type]
        )
        self._pool.extend(keypairs)
