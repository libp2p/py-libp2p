#!/usr/bin/env python3
"""
Interop listener (responder) for Noise_XXhfs_25519+MLKEM768_ChaChaPoly_SHA256
(/noise-mlkem768-hfs/0.2.0), using py-libp2p's PatternXXhfs.

Accepts one connection, completes the handshake, sends one greeting, checks the
reply, prints INTEROP_OK and exits. Run with PYTHONPATH set to the repo root.

    python scripts/interop_listen_mlkem768.py [--port N]   (default 9998)
"""

import argparse
import asyncio
import sys
from typing import cast

from _interop_io import AsyncioTCPConn, out, read_greeting, send_greeting

from libp2p.abc import IRawConnection
from libp2p.crypto.ed25519 import create_new_key_pair as ed25519_key_pair
from libp2p.crypto.x25519 import create_new_key_pair as x25519_key_pair
from libp2p.peer.id import ID
from libp2p.security.noise.pq.kem_backends import make_fast_kem
from libp2p.security.noise.pq.patterns_pq import PatternXXhfs


async def main(port: int) -> None:
    identity = ed25519_key_pair()
    local_peer = ID.from_pubkey(identity.public_key)
    out(f"LOCAL {local_peer}")

    accepted: asyncio.Queue[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
        asyncio.Queue(maxsize=1)
    )
    server = await asyncio.start_server(
        lambda r, w: accepted.put_nowait((r, w)), "127.0.0.1", port
    )
    out(f"READY {port}")
    reader, writer = await accepted.get()
    server.close()

    conn = AsyncioTCPConn(reader, writer, is_initiator=False)
    pattern = PatternXXhfs(
        local_peer=local_peer,
        libp2p_privkey=identity.private_key,
        noise_static_key=x25519_key_pair().private_key,
        kem=make_fast_kem(),
    )
    session = await pattern.handshake_inbound(cast(IRawConnection, conn))
    out(f"PEER {session.remote_peer}")
    await send_greeting(session)
    await read_greeting(session)
    out("INTEROP_OK")
    await session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9998)
    try:
        asyncio.run(main(parser.parse_args().port))
    except Exception as exc:  # harness boundary: report and exit non-zero
        print(f"ERROR {exc!r}", file=sys.stderr, flush=True)
        sys.exit(1)
