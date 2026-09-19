#!/usr/bin/env python3
"""
Interop dialer (initiator) for Noise_XXhfs_25519+MLKEM768_ChaChaPoly_SHA256
(/noise-mlkem768-hfs/0.2.0), using py-libp2p's PatternXXhfs.

Earlier versions of this script carried a standalone re-implementation of the
handshake; interop results must exercise the library, so it now drives
PatternXXhfs.handshake_outbound directly. remote_peer=None is used because the
listener's identity is not known in advance; the runner instead checks that the
PEER printed here equals the LOCAL the listener printed.

    python scripts/interop_dial_mlkem768.py [--port N]   (default 9999)
"""

import argparse
import asyncio
import sys
from typing import cast

from _interop_io import (
    AsyncioTCPConn,
    out,
    read_greeting,
    send_greeting,
    with_deadline,
)

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

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    conn = AsyncioTCPConn(reader, writer, is_initiator=True)
    pattern = PatternXXhfs(
        local_peer=local_peer,
        libp2p_privkey=identity.private_key,
        noise_static_key=x25519_key_pair().private_key,
        kem=make_fast_kem(),
    )
    session = await pattern.handshake_outbound(cast(IRawConnection, conn), None)
    out(f"PEER {session.get_remote_peer()}")
    await read_greeting(session)
    await send_greeting(session)
    out("INTEROP_OK")
    await session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9999)
    try:
        # Overall deadline: a silent listener must not pin this process.
        asyncio.run(with_deadline(main(parser.parse_args().port), "interop dialer run"))
    except Exception as exc:  # harness boundary: report and exit non-zero
        print(f"ERROR {exc!r}", file=sys.stderr, flush=True)
        sys.exit(1)
