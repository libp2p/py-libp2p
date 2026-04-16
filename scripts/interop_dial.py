"""
Phase 5 live interop: Python dialer connecting to the JS NoiseHFS listener.

Usage:
    # Terminal 1 — start the JS listener:
    node js-libp2p-noise/scripts/node-listener.mjs

    # Terminal 2 — run this dialer:
    cd py-libp2p
    python scripts/interop_dial.py

Verifies that Python (py-libp2p) and JavaScript (js-libp2p-noise) can
complete a Noise_XXhfs_25519+XWing_ChaChaPoly_SHA256 handshake over a
real TCP connection and exchange encrypted messages.
"""

import asyncio
import logging
import sys

import anyio
import anyio.abc
from libp2p.crypto.ed25519 import create_new_key_pair as ed25519_keypair
from libp2p.crypto.x25519 import create_new_key_pair as x25519_keypair
from libp2p.peer.id import ID
from libp2p.security.noise.pq.patterns_pq import PatternXXhfs
from libp2p.security.noise.pq.kem import XWingKem

HOST = "127.0.0.1"
PORT = 8000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("interop_dial")


class RawTCPConn:
    """Minimal IRawConnection wrapping an anyio SocketStream.

    Adapts anyio's ByteStream to the read/write/close interface that
    NoisePacketReadWriter (and thus PatternXXhfs) expects.
    """

    is_initiator: bool = True

    def __init__(self, stream: anyio.abc.ByteStream) -> None:
        self._stream = stream

    async def read(self, n: int | None = None) -> bytes:
        if n is None:
            return await self._stream.receive(65536)
        return await self._stream.receive(n)

    async def write(self, data: bytes) -> None:
        await self._stream.send(data)

    async def close(self) -> None:
        await self._stream.aclose()

    def get_transport_addresses(self) -> list:
        return []


async def main() -> None:
    # ── Key material ────────────────────────────────────────────────────────────
    # libp2p identity (Ed25519) — used in the Noise handshake payload signature
    libp2p_kp = ed25519_keypair()
    local_peer = ID.from_pubkey(libp2p_kp.public_key)

    # Noise static key (X25519) — used in the XX handshake s/se tokens
    noise_kp = x25519_keypair()
    noise_static = noise_kp.private_key

    logger.info("Local peer ID: %s", local_peer)

    # ── Connect ─────────────────────────────────────────────────────────────────
    logger.info("Connecting to JS listener at %s:%d", HOST, PORT)
    async with await anyio.connect_tcp(HOST, PORT) as stream:
        conn = RawTCPConn(stream)
        logger.info("TCP connection established")

        # ── Handshake ───────────────────────────────────────────────────────────
        # We don't know the JS peer ID in advance (it's freshly generated each
        # run), so we pass a dummy peer ID and rely on signature verification.
        # For a production scenario you'd pass the actual expected peer ID here.
        pattern = PatternXXhfs(
            local_peer=local_peer,
            libp2p_privkey=libp2p_kp.private_key,
            noise_static_key=noise_static,
            kem=XWingKem(),
        )

        logger.info("Starting XXhfs handshake (Python = initiator)...")

        # Pass None for remote_peer — the JS listener is freshly keyed each run
        # so its peer ID isn't known in advance. The signature is still fully
        # verified; we just don't constrain which peer ID is acceptable.
        try:
            secure_conn = await pattern.handshake_outbound(conn, None)
        except Exception as exc:
            logger.error("Handshake failed: %s", exc)
            raise

        logger.info(
            "Handshake complete! Remote peer: %s",
            secure_conn.get_remote_peer(),
        )

        # ── Exchange messages ────────────────────────────────────────────────────
        # Read greeting from JS — SecureSession.read() decrypts one Noise message
        js_greeting_raw = await secure_conn.read()
        js_greeting = js_greeting_raw.decode().strip()
        logger.info('Received from JS: "%s"', js_greeting)

        if js_greeting != "hello from JS":
            logger.error("Unexpected greeting from JS: %r", js_greeting)
            sys.exit(1)

        # Send reply to JS — SecureSession.write() encrypts one Noise message
        await secure_conn.write(b"hello from Python\n")
        logger.info('Sent to JS: "hello from Python"')

        print()
        print("=" * 60)
        print("INTEROP SUCCESS")
        print("Python <-> JavaScript NoiseHFS handshake complete.")
        print(f"Protocol: Noise_XXhfs_25519+XWing_ChaChaPoly_SHA256")
        print(f"Local peer:  {local_peer}")
        print(f"Remote peer: {secure_conn.get_remote_peer()}")
        print("=" * 60)


if __name__ == "__main__":
    anyio.run(main)
