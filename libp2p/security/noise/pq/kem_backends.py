"""
Fast KEM backends for the Noise XXhfs handshake.

Two components are provided:

LibOQSXWingKem
    X-Wing built on liboqs (Open Quantum Safe C library).
    Requires `pip install liboqs-python` AND the liboqs shared library.
    Typical performance: keygen ~0.15 ms, encap ~0.12 ms, decap ~0.10 ms —
    roughly 100-200x faster than the pure-Python kyber-py backend.

    Installation:
        # Windows: download the prebuilt DLL from the OQS releases page and
        # place liboqs.dll in the same directory as oqs/__init__.py, then:
        pip install liboqs-python

        # Linux/macOS:
        sudo apt install liboqs-dev   # or brew install liboqs
        pip install liboqs-python

KeypairPool
    Pre-computes KEM keypairs during idle time so keygen does not fall on
    the connection critical path. Works with any IKem backend. With the
    pure-Python kyber-py backend, keygen costs ~20 ms; a pool of 3 pre-generated
    keypairs means 3 connections can complete their KEM handshake without paying
    any keygen cost at all. Background refill uses asyncio.to_thread() on
    Python ≥ 3.9 so the event loop is never blocked.

    Usage:
        from libp2p.security.noise.pq.kem import MLKEM768Kem
        from libp2p.security.noise.pq.kem_backends import KeypairPool

        pool = await KeypairPool.create(MLKEM768Kem(), min_size=3)
        pk, sk = pool.acquire()   # instant — no keygen on critical path
"""

from __future__ import annotations

import asyncio
from collections import deque
import logging
from typing import TYPE_CHECKING

from ._xwing import _xwing_combine

if TYPE_CHECKING:
    from .kem import IKem

logger = logging.getLogger(__name__)

# Cached result of the liboqs availability probe. None = not yet checked,
# True = available, False = unavailable. Avoids re-running the 5-second
# oqs auto-install wait on every make_fast_kem() / LibOQSXWingKem() call.
_LIBOQS_AVAILABLE: bool | None = None

_ML_KEM_768_PK_SIZE = 1184
_ML_KEM_768_CT_SIZE = 1088
_X25519_KEY_SIZE = 32


class LibOQSXWingKem:
    """
    X-Wing KEM built on liboqs (C library via liboqs-python).

    Uses OQS_KEM_ml_kem_768 for the ML-KEM-768 component and
    PyNaCl (libsodium) for X25519 — both C extensions, so no
    Python bottleneck in the inner loops.

    Raises ImportError on construction if liboqs-python or liboqs.dll
    is not available; fall back to XWingKem (kyber-py) in that case.
    """

    PUBKEY_LEN = 1216  # 1184 + 32
    CT_LEN = 1120  # 1088 + 32
    SS_LEN = 32
    SK_LEN = 2432  # 2400 ML-KEM-768 dk + 32 X25519 sk

    def __init__(self) -> None:
        global _LIBOQS_AVAILABLE
        # Fast path: skip the 5-second auto-install wait if we already know
        # the C library is absent.
        if _LIBOQS_AVAILABLE is False:
            raise ImportError(
                "LibOQSXWingKem requires the liboqs C library (not available). "
                "See: https://github.com/open-quantum-safe/liboqs-python"
            )
        # liboqs-python may raise ImportError, RuntimeError, SystemExit(1)
        # (git-clone auto-install), or OSError (Windows temp-dir cleanup race).
        # Catch all and convert to ImportError so callers can gracefully fall back.
        try:
            from nacl.bindings import crypto_scalarmult, crypto_scalarmult_base
            import nacl.utils
            import oqs  # type: ignore[import-error]

            _LIBOQS_AVAILABLE = True
        except (ImportError, RuntimeError, SystemExit, OSError) as e:
            _LIBOQS_AVAILABLE = False
            raise ImportError(
                "LibOQSXWingKem requires the liboqs C library and PyNaCl. "
                "See: https://github.com/open-quantum-safe/liboqs-python. "
                f"Original error: {e}"
            ) from e

        self._oqs = oqs  # type: ignore[name-defined]
        self._scalarmult = crypto_scalarmult  # type: ignore[name-defined]
        self._scalarmult_base = crypto_scalarmult_base  # type: ignore[name-defined]
        self._nacl_random = nacl.utils.random  # type: ignore[name-defined]

    def keygen(self) -> tuple[bytes, bytes]:
        """
        Generate an X-Wing keypair via liboqs + libsodium.

        Returns:
            (pk, sk) where pk = ml_kem_ek || x25519_pk (1216 B),
                           sk = ml_kem_dk || x25519_sk (2432 B).

        """
        with self._oqs.KeyEncapsulation("ML-KEM-768") as kem:  # type: ignore[arg-type]
            ml_pk = kem.generate_keypair()  # type: ignore[union-attr]
            ml_sk = kem.export_secret_key()  # type: ignore[union-attr]

        x_sk = self._nacl_random(_X25519_KEY_SIZE)
        x_pk = bytes(self._scalarmult_base(x_sk))
        return ml_pk + x_pk, ml_sk + x_sk

    def encapsulate(self, pk: bytes) -> tuple[bytes, bytes]:
        """
        Encapsulate to an X-Wing public key.

        Args:
            pk: 1216-byte X-Wing public key.

        Returns:
            (ct, ss) where ct = ml_kem_ct || x25519_eph_pk (1120 B),
                           ss = 32-byte X-Wing shared secret.

        """
        if len(pk) != self.PUBKEY_LEN:
            raise ValueError(f"pk must be {self.PUBKEY_LEN} bytes, got {len(pk)}")

        ml_pk = pk[:_ML_KEM_768_PK_SIZE]
        x_pk_r = pk[_ML_KEM_768_PK_SIZE:]

        with self._oqs.KeyEncapsulation("ML-KEM-768") as kem:  # type: ignore[arg-type]
            ml_ct, ss_mlkem = kem.encap_secret(ml_pk)  # type: ignore[union-attr]

        x_eph_sk = self._nacl_random(_X25519_KEY_SIZE)
        x_eph_pk = bytes(self._scalarmult_base(x_eph_sk))
        ss_x25519 = bytes(self._scalarmult(x_eph_sk, x_pk_r))

        ss = _xwing_combine(ss_mlkem, ss_x25519, x_eph_pk, x_pk_r)
        return ml_ct + x_eph_pk, ss

    def decapsulate(self, ct: bytes, sk: bytes) -> bytes:
        """
        Decapsulate an X-Wing ciphertext.

        Args:
            ct: 1120-byte X-Wing ciphertext.
            sk: 2432-byte X-Wing secret key.

        Returns:
            32-byte X-Wing shared secret.

        """
        if len(ct) != self.CT_LEN:
            raise ValueError(f"ct must be {self.CT_LEN} bytes, got {len(ct)}")
        if len(sk) != self.SK_LEN:
            raise ValueError(f"sk must be {self.SK_LEN} bytes, got {len(sk)}")

        ml_sk = sk[:2400]
        x_sk_r = sk[2400:]
        ml_ct = ct[:_ML_KEM_768_CT_SIZE]
        x_eph_pk = ct[_ML_KEM_768_CT_SIZE:]

        with self._oqs.KeyEncapsulation("ML-KEM-768", secret_key=ml_sk) as kem:  # type: ignore[arg-type]
            ss_mlkem = kem.decap_secret(ml_ct)  # type: ignore[union-attr]

        ss_x25519 = bytes(self._scalarmult(x_sk_r, x_eph_pk))
        x_pk_r = bytes(self._scalarmult_base(x_sk_r))
        return _xwing_combine(ss_mlkem, ss_x25519, x_eph_pk, x_pk_r)


def make_fast_kem() -> IKem:
    """
    Return an ML-KEM-768 KEM backend.

    Uses kyber-py (pure Python). For a faster alternative, a liboqs-backed
    MLKEM768Kem can be added following the LibOQSXWingKem pattern.
    """
    from .kem import MLKEM768Kem

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
        one synchronously (fallback — should not happen in normal operation).
        Schedules an async refill if the pool drops below min_size.
        """
        if self._pool:
            kp = self._pool.popleft()
        else:
            logger.warning("KeypairPool exhausted — generating synchronously")
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
            return  # no event loop — skip background refill
        self._refill_task = loop.create_task(self._async_fill())
        self._refill_task.add_done_callback(self._on_refill_done)

    def _on_refill_done(self, task: asyncio.Task[None]) -> None:
        self._refill_task = None
        if task.cancelled():
            return  # event loop shutting down — normal
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
