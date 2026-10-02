"""
Shared scaffolding for the PQ (XXhfs) handshake tests.

Holds the in-memory connection pair, the ``PatternXXhfs`` factory and the KEM
backend parametrisation used by more than one test module, so the pieces are
defined once.
"""

import math

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.abc import IRawConnection
from libp2p.connection_types import ConnectionType
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.x25519 import X25519PrivateKey
from libp2p.peer.id import ID
from libp2p.security.noise.pq.kem import IKem, MLKEM768Kem, MLKEM768NativeKem
from libp2p.security.noise.pq.patterns_pq import PatternXXhfs

# 2-byte big-endian length prefix, per NoisePacketReadWriter.
_LEN_PREFIX_BYTES = 2

# ---------------------------------------------------------------------------
# KEM backend parametrisation
#
# Every end-to-end test that does not say otherwise runs on whichever backend
# make_fast_kem() picks, which is the native one wherever it is available. The
# names below let a test run the same handshake on each backend explicitly, so
# kyber-py keeps handshake-level coverage on a machine where the native
# backend works.
# ---------------------------------------------------------------------------

PURE_KEM = "kyber-py"
NATIVE_KEM = "native"


def _native_kem_unavailable() -> str | None:
    """Return why the native backend cannot run here, or None when it can."""
    try:
        MLKEM768NativeKem()
    except Exception as exc:  # pragma: no cover - depends on the environment
        return f"native ML-KEM-768 backend unavailable: {exc}"
    return None


NATIVE_KEM_SKIP_REASON = _native_kem_unavailable()

#: pytest params covering both KEM backends. The native one is skipped rather
#: than failed when this build of ``cryptography`` cannot run ML-KEM.
KEM_BACKENDS = [
    pytest.param(PURE_KEM, id=PURE_KEM),
    pytest.param(
        NATIVE_KEM,
        id=NATIVE_KEM,
        marks=pytest.mark.skipif(
            NATIVE_KEM_SKIP_REASON is not None,
            reason=NATIVE_KEM_SKIP_REASON or "",
        ),
    ),
]


def make_kem(backend: str) -> IKem:
    """Build the named KEM backend. ``backend`` is PURE_KEM or NATIVE_KEM."""
    if backend == NATIVE_KEM:
        return MLKEM768NativeKem()
    if backend == PURE_KEM:
        return MLKEM768Kem()
    raise ValueError(f"unknown KEM backend {backend!r}")


class MemoryConn(IRawConnection):
    """
    Async in-memory bidirectional stream backed by trio memory channels.

    Implements IRawConnection for use in handshake tests.
    """

    is_initiator: bool = False

    def __init__(
        self,
        send_chan: trio.MemorySendChannel[bytes],
        recv_chan: trio.MemoryReceiveChannel[bytes],
    ) -> None:
        self._send = send_chan
        self._recv = recv_chan
        self._buf = bytearray()

    async def read(self, n: int | None = None) -> bytes:
        if n == 0:
            # A real stream returns immediately for a zero-byte read; blocking
            # here would deadlock on a legitimately empty (zero-length) frame.
            return b""
        while not self._buf:
            try:
                chunk = await self._recv.receive()
            except trio.EndOfChannel:
                return b""
            self._buf.extend(chunk)
        if n is None:
            data = bytes(self._buf)
            self._buf.clear()
            return data
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data

    async def write(self, data: bytes) -> None:
        await self._send.send(bytes(data))

    async def close(self) -> None:
        await self._send.aclose()

    def get_remote_address(self) -> tuple[str, int] | None:
        return None

    def get_transport_addresses(self) -> list[Multiaddr]:
        return []

    def get_connection_type(self) -> ConnectionType:
        return ConnectionType.UNKNOWN


class WriteCapture(IRawConnection):
    """Wraps a connection and records every call to write()."""

    is_initiator: bool = False

    def __init__(self, inner: MemoryConn) -> None:
        self._inner = inner
        self.writes: list[bytes] = []

    async def read(self, n: int | None = None) -> bytes:
        return await self._inner.read(n)

    async def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))
        await self._inner.write(data)

    async def close(self) -> None:
        await self._inner.close()

    def get_remote_address(self) -> tuple[str, int] | None:
        return None

    def get_transport_addresses(self) -> list[Multiaddr]:
        return []

    def get_connection_type(self) -> ConnectionType:
        return ConnectionType.UNKNOWN


def make_conn_pair() -> tuple[MemoryConn, MemoryConn]:
    """Create a pair of in-memory connections wired together."""
    a_to_b_send, a_to_b_recv = trio.open_memory_channel(math.inf)
    b_to_a_send, b_to_a_recv = trio.open_memory_channel(math.inf)
    init_conn = MemoryConn(a_to_b_send, b_to_a_recv)
    resp_conn = MemoryConn(b_to_a_send, a_to_b_recv)
    return init_conn, resp_conn


def make_pattern(kem: IKem | None = None) -> tuple[PatternXXhfs, object, object, ID]:
    """
    Create a fresh PatternXXhfs with newly-generated keys.

    ``kem`` pins the KEM backend; the default leaves the choice to
    ``make_fast_kem()``, which is what production does.
    """
    kp = create_new_key_pair()
    noise_key = X25519PrivateKey.new()
    peer = ID.from_pubkey(kp.public_key)
    pattern = PatternXXhfs(
        local_peer=peer,
        libp2p_privkey=kp.private_key,
        noise_static_key=noise_key,
        kem=kem,
    )
    return pattern, kp, noise_key, peer


async def write_frame(conn: IRawConnection, body: bytes) -> None:
    """Write one raw length-prefixed handshake frame, bypassing any parser."""
    await conn.write(len(body).to_bytes(_LEN_PREFIX_BYTES, "big") + body)


async def _read_exactly(conn: IRawConnection, size: int) -> bytes:
    chunks: list[bytes] = []
    received = 0
    while received < size:
        chunk = await conn.read(size - received)
        if not chunk:
            raise EOFError(f"connection closed after {received} of {size} bytes")
        chunks.append(chunk)
        received += len(chunk)
    return b"".join(chunks)


async def read_frame(conn: IRawConnection) -> bytes:
    """Read one raw length-prefixed handshake frame and return its body."""
    size = int.from_bytes(await _read_exactly(conn, _LEN_PREFIX_BYTES), "big")
    return await _read_exactly(conn, size) if size else b""
