#!/usr/bin/env python3
import argparse
import logging
import sys

from multiaddr import Multiaddr
import redis.asyncio as redis  # type: ignore[import-untyped]
import trio
from trio_asyncio import aio_as_trio, open_loop  # type: ignore[import-untyped]

from libp2p import new_host
from libp2p.abc import IHost, INetStream
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID as PeerID

logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(levelname)s [py-peer] %(message)s"
)
logger = logging.getLogger("py-peer")

PING_PROTOCOL = TProtocol("/ipfs/ping/1.0.0")
COORDINATION_KEY_PREFIX = "interop:webrtc"


class PyLibp2pPeer:
    def __init__(self, role: str, redis_client: redis.Redis, listen_port: int = 9090):
        self.role = role
        self.redis = redis_client
        self.host: IHost | None = None
        self.peer_id: PeerID | None = None
        self.listen_port = listen_port

    async def setup_host(self) -> None:
        key_pair = create_new_key_pair()
        self.peer_id = PeerID.from_pubkey(key_pair.public_key)

        self.host = new_host(
            key_pair=key_pair,
            listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
        )

    async def start_listener(self) -> None:
        if self.host is None:
            raise RuntimeError("Host not initialized")
        if self.peer_id is None:
            raise RuntimeError("Peer ID not initialized")

        webrtc_addr = Multiaddr(f"/ip4/0.0.0.0/udp/{self.listen_port}/webrtc")
        await self.host.get_network().listen(webrtc_addr)

        self.host.set_stream_handler(PING_PROTOCOL, self.ping_handler)

        addrs = self.host.get_addrs()
        if addrs:
            addr_with_peer = f"{addrs[0]}/p2p/{self.peer_id}"
            await aio_as_trio(
                self.redis.set(
                    f"{COORDINATION_KEY_PREFIX}:listener:addr", addr_with_peer, ex=300
                )
            )

        await aio_as_trio(
            self.redis.set(f"{COORDINATION_KEY_PREFIX}:listener:ready", "1", ex=300)
        )

        try:
            while True:
                await trio.sleep(1)
        except trio.Cancelled:
            pass

    async def ping_handler(self, stream: INetStream) -> None:
        try:
            payload = await stream.read(32)
            await stream.write(payload)
            await stream.close()
        except Exception:
            pass

    async def start_dialer(self) -> None:
        if self.host is None:
            raise RuntimeError("Host not initialized")

        max_wait = 60
        for _ in range(max_wait):
            ready = await aio_as_trio(
                self.redis.get(f"{COORDINATION_KEY_PREFIX}:listener:ready")
            )
            if ready:
                break
            await trio.sleep(1)
        else:
            raise TimeoutError("Listener not ready")

        listener_addr_str = await aio_as_trio(
            self.redis.get(f"{COORDINATION_KEY_PREFIX}:listener:addr")
        )
        if not listener_addr_str:
            raise ValueError("Listener address missing")

        listener_addr = Multiaddr(listener_addr_str.decode())

        listener_peer_id = None
        for proto in listener_addr.protocols():
            if proto.name == "p2p":
                peer_id_str = listener_addr.value_for_protocol(proto.code)
                if peer_id_str is None:
                    continue
                listener_peer_id = PeerID.from_base58(peer_id_str)
                break

        if not listener_peer_id:
            raise ValueError("Invalid multiaddr: missing peer ID")

        self.host.get_peerstore().add_addrs(listener_peer_id, [listener_addr], 10000)

        try:
            await self.host.connect(listener_peer_id)
            await aio_as_trio(
                self.redis.set(
                    f"{COORDINATION_KEY_PREFIX}:connection:status",
                    "connected",
                    ex=300,
                )
            )
            await self.test_ping(listener_peer_id)

        except Exception as e:
            await aio_as_trio(
                self.redis.set(
                    f"{COORDINATION_KEY_PREFIX}:connection:status",
                    f"failed:{e}",
                    ex=300,
                )
            )
            raise

    async def test_ping(self, peer_id: PeerID) -> None:
        if self.host is None:
            raise RuntimeError("Host not initialized")

        try:
            stream = await self.host.new_stream(peer_id, [PING_PROTOCOL])

            import secrets

            ping_payload = secrets.token_bytes(32)
            await stream.write(ping_payload)

            pong_payload = await stream.read(32)

            if ping_payload == pong_payload:
                await aio_as_trio(
                    self.redis.set(
                        f"{COORDINATION_KEY_PREFIX}:ping:status", "passed", ex=300
                    )
                )
            else:
                await aio_as_trio(
                    self.redis.set(
                        f"{COORDINATION_KEY_PREFIX}:ping:status",
                        "failed:mismatch",
                        ex=300,
                    )
                )

            await stream.close()

        except Exception as e:
            await aio_as_trio(
                self.redis.set(
                    f"{COORDINATION_KEY_PREFIX}:ping:status", f"failed:{e}", ex=300
                )
            )
            raise

    async def run(self) -> None:
        await self.setup_host()

        if self.role == "listener":
            await self.start_listener()
        elif self.role == "dialer":
            await self.start_dialer()
        else:
            raise ValueError("Invalid role")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["listener", "dialer"], required=True)
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument("--redis-host", default="localhost")
    parser.add_argument("--redis-port", type=int, default=6379)
    args = parser.parse_args()

    redis_url = f"redis://{args.redis_host}:{args.redis_port}"

    async def run_with_redis() -> None:
        async with open_loop():
            try:
                redis_client = await aio_as_trio(
                    redis.from_url(redis_url, decode_responses=False)
                )
                await aio_as_trio(redis_client.ping())
            except Exception:
                sys.exit(1)

            peer = PyLibp2pPeer(args.role, redis_client, listen_port=args.port)

            try:
                await peer.run()
            except KeyboardInterrupt:
                pass
            except Exception:
                sys.exit(1)
            finally:
                await aio_as_trio(redis_client.close())

    trio.run(run_with_redis)
