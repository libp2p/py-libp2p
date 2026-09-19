"""
KEM helpers for the Noise XXhfs handshake.

``make_fast_kem()`` returns the default KEM for the suite, and ``KeypairPool``
pre-computes keypairs so a handshake does not pay ML-KEM keygen inline.

The default backend is the native one, ``MLKEM768NativeKem``, built on
``cryptography``'s ML-KEM. kyber-py (pure Python) is the fallback when the
native backend is unavailable: see the note on ``make_fast_kem``.

The choice is a property of the build, not of the connection, so it is made
once per process and memoised in ``_select_kem_class``. Falling back to
kyber-py is logged at warning level, because kyber-py is not constant time
and its own metadata says it must not be used for cryptographic applications.
"""

from __future__ import annotations

import asyncio
from collections import deque
import functools
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .kem import IKem

logger = logging.getLogger(__name__)

_ML_KEM_768_PK_SIZE = 1184
_ML_KEM_768_CT_SIZE = 1088
_X25519_KEY_SIZE = 32


_FALLBACK_WARNING = (
    "post-quantum Noise is falling back to the pure-Python kyber-py "
    "ML-KEM-768 backend, because the native one is unavailable (%s). "
    "kyber-py's own package metadata states that it is not constant time "
    "and must not be used for cryptographic applications, so this peer's "
    "ML-KEM decapsulation is exposed to timing side channels and is roughly "
    "two orders of magnitude slower. Install a build of cryptography with "
    "ML-KEM support (cryptography>=48.0.0 on OpenSSL 3.5.0+, AWS-LC or "
    "BoringSSL) to get the native backend back."
)

_NO_BACKEND_ERROR = (
    "no working ML-KEM-768 backend is available, so the post-quantum Noise "
    "suite cannot run.\n"
    "  native (cryptography): {native}\n"
    "  fallback (kyber-py):   {pure}\n"
    "Install a build of cryptography with ML-KEM support "
    "(cryptography>=48.0.0 on OpenSSL 3.5.0+, AWS-LC or BoringSSL), or "
    "install the pure-Python fallback with: pip install 'libp2p[pq]'"
)


@functools.lru_cache(maxsize=1)
def _select_kem_class() -> type[IKem]:
    """
    Decide once which ML-KEM-768 backend this process uses.

    Selection probes ``cryptography`` for ML-KEM support, so it is memoised:
    it is a property of the build, not of the connection, and it used to be
    re-run for every inbound connection before the peer had authenticated
    anything.

    Tests that change the availability of a backend must call
    ``_select_kem_class.cache_clear()``.
    """
    from .kem import MLKEM768Kem, MLKEM768NativeKem

    try:
        MLKEM768NativeKem()
    except Exception as native_exc:
        # Deliberately broader than ImportError: a renamed upstream symbol
        # (AttributeError) or an OpenSSL-level InternalError must fall back
        # rather than escape raw from a connection setup path.
        logger.warning(_FALLBACK_WARNING, native_exc)
        try:
            MLKEM768Kem()
        except Exception as pure_exc:
            raise ImportError(
                _NO_BACKEND_ERROR.format(native=native_exc, pure=pure_exc)
            ) from pure_exc
        return MLKEM768Kem
    return MLKEM768NativeKem


def make_fast_kem() -> IKem:
    """
    Return the fastest available ML-KEM-768 KEM backend.

    Prefers :class:`~libp2p.security.noise.pq.kem.MLKEM768NativeKem`, which
    uses ``cryptography``'s native ML-KEM. Falls back to the pure-Python
    :class:`~libp2p.security.noise.pq.kem.MLKEM768Kem` (kyber-py) when the
    native one is unavailable, which happens when ``cryptography`` predates
    48.0.0 or was built without ML-KEM support. The two backends interoperate
    on the wire, so the choice is local to each peer.

    The choice is made once per process; only the instance is fresh. When
    neither backend works this raises a single ``ImportError`` naming both
    causes.
    """
    return _select_kem_class()()


class KeypairPool:
    """
    Pre-computes KEM keypairs during idle time to eliminate keygen latency
    on the connection critical path.

    A pool of 3 pre-generated keypairs means 3 handshakes can proceed without
    paying any keygen cost. Background refill uses ``asyncio.to_thread()`` so
    the event loop is not blocked.

    How much this is worth depends entirely on the backend, and the case for
    it is much weaker than it was. On kyber-py, keygen costs a few
    milliseconds and dominates the handshake, so pooling is close to
    essential. On the native backend, which is now the default, keygen is
    around 0.3 ms, the same order as encapsulation, so the pool removes a
    small constant rather than the main cost. Measure before adding one: see
    ``benchmarks/bench_noise_pq.py``, which reports both backends.

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
