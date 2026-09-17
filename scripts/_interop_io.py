r"""
Shared pieces of the cross-implementation interop harness.

Every implementation's harness speaks the same contract: the listener sends
``hello from <Impl>\n`` first, the dialer replies in kind, and both print
LOCAL/PEER/SENT/RECV/INTEROP_OK on stdout.
"""

import asyncio

from libp2p.abc import ISecureConn
from libp2p.io.abc import ReadWriteCloser

IMPL = "Python"
GREETING_PREFIX = "hello from "


class AsyncioTCPConn(ReadWriteCloser):
    """Wrap an asyncio stream pair as a py-libp2p raw connection."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        is_initiator: bool,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self.is_initiator = is_initiator
        self._peername: tuple[str, int] | None = writer.get_extra_info("peername")

    async def read(self, n: int | None = None) -> bytes:
        if n is None or n < 0:
            return await self._reader.read(65536)
        return await self._reader.readexactly(n)

    async def write(self, data: bytes) -> None:
        self._writer.write(data)
        await self._writer.drain()

    async def close(self) -> None:
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except (ConnectionError, OSError):
            pass

    def get_remote_address(self) -> tuple[str, int] | None:
        return self._peername


def out(line: str) -> None:
    print(line, flush=True)


async def send_greeting(session: ISecureConn) -> None:
    await session.write(f"{GREETING_PREFIX}{IMPL}\n".encode())
    out(f"SENT {GREETING_PREFIX}{IMPL}")


async def read_greeting(session: ISecureConn) -> str:
    buf = b""
    while b"\n" not in buf:
        # SecureSession.read(n) blocks until *exactly* n bytes have arrived
        # (it keeps pulling transport messages until the total reaches n),
        # unlike a raw socket recv(). A one-line greeting is far shorter
        # than any fixed size we could pick, so request n=None: that reads
        # exactly one already-framed transport message and returns
        # immediately, which is what we want here.
        chunk = await session.read()
        if not chunk:
            raise EOFError("connection closed before a greeting arrived")
        buf += chunk
    line = buf.split(b"\n", 1)[0].decode()
    out(f"RECV {line}")
    if not line.startswith(GREETING_PREFIX) or line == GREETING_PREFIX:
        raise ValueError(f"unexpected greeting {line!r}")
    return line
