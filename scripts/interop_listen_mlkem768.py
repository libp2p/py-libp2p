#!/usr/bin/env python3
"""
Standalone TCP listener for Noise_XXhfs_25519+ML-KEM-768_ChaChaPoly_SHA256.

Runs the responder side of the XXhfs handshake using the updated py-libp2p
library, then prints the initiator's peer ID and exits.

Usage:
    python scripts/interop_listen_mlkem768.py [--port N]   (default 9998)

Protocol:  Noise_XXhfs_25519+ML-KEM-768_ChaChaPoly_SHA256
Protocol ID: /noise-mlkem768-hfs/0.1.0
"""

import argparse
import asyncio
import sys
from typing import cast

from libp2p.crypto.ed25519 import create_new_key_pair as ed25519_key_pair
from libp2p.crypto.x25519 import create_new_key_pair as x25519_key_pair
from libp2p.io.abc import ReadWriteCloser
from libp2p.peer.id import ID
from libp2p.security.noise.pq.kem_backends import make_fast_kem
from libp2p.security.noise.pq.patterns_pq import PatternXXhfs


class AsyncioTCPConn(ReadWriteCloser):
    """Wrap asyncio StreamReader/StreamWriter as a py-libp2p ReadWriteCloser."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._reader = reader
        self._writer = writer
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
        except Exception:
            pass

    def get_remote_address(self) -> tuple[str, int] | None:
        return self._peername


async def handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    addr = writer.get_extra_info("peername")
    print(f"Connection from {addr[0]}:{addr[1]}", flush=True)

    # Generate ephemeral identities for this test
    libp2p_keypair = ed25519_key_pair()
    noise_kp = x25519_key_pair()
    local_peer = ID.from_pubkey(libp2p_keypair.public_key)
    kem = make_fast_kem()

    handshake = PatternXXhfs(
        local_peer=local_peer,
        libp2p_privkey=libp2p_keypair.private_key,
        noise_static_key=noise_kp.private_key,
        kem=kem,
    )
    conn = AsyncioTCPConn(reader, writer)
    session = await handshake.handshake_inbound(cast(ReadWriteCloser, conn))

    print(f"PEER {session.remote_peer}", flush=True)
    await conn.close()


async def main(port: int) -> None:
    server = await asyncio.start_server(handle, "127.0.0.1", port)
    addr = server.sockets[0].getsockname()
    print(f"READY {addr[1]}", flush=True)

    async with server:
        # Accept exactly one connection, then exit
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9998)
    args = parser.parse_args()
    try:
        asyncio.run(main(args.port))
    except KeyboardInterrupt:
        sys.exit(0)
