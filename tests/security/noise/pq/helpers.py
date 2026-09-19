"""
Shared scaffolding for the PQ (XXhfs) handshake tests.

Holds the in-memory connection pair and the ``PatternXXhfs`` factory used by
more than one test module, so the pieces are defined once.
"""

import math

from multiaddr import Multiaddr
import trio

from libp2p.abc import IRawConnection
from libp2p.connection_types import ConnectionType
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.x25519 import X25519PrivateKey
from libp2p.peer.id import ID
from libp2p.security.noise.pq.patterns_pq import PatternXXhfs

# 2-byte big-endian length prefix, per NoisePacketReadWriter.
_LEN_PREFIX_BYTES = 2


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


def make_pattern() -> tuple[PatternXXhfs, object, object, ID]:
    """Create a fresh PatternXXhfs with newly-generated keys."""
    kp = create_new_key_pair()
    noise_key = X25519PrivateKey.new()
    peer = ID.from_pubkey(kp.public_key)
    pattern = PatternXXhfs(
        local_peer=peer,
        libp2p_privkey=kp.private_key,
        noise_static_key=noise_key,
    )
    return pattern, kp, noise_key, peer


async def write_frame(conn: IRawConnection, body: bytes) -> None:
    """Write one raw length-prefixed handshake frame, bypassing any parser."""
    await conn.write(len(body).to_bytes(_LEN_PREFIX_BYTES, "big") + body)


async def _read_exactly(conn: IRawConnection, size: int) -> bytes:
    buf = b""
    while len(buf) < size:
        chunk = await conn.read(size - len(buf))
        if not chunk:
            raise EOFError(f"connection closed after {len(buf)} of {size} bytes")
        buf += chunk
    return buf


async def read_frame(conn: IRawConnection) -> bytes:
    """Read one raw length-prefixed handshake frame and return its body."""
    size = int.from_bytes(await _read_exactly(conn, _LEN_PREFIX_BYTES), "big")
    return await _read_exactly(conn, size) if size else b""
