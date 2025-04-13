import logging

from multiaddr import (
    Multiaddr,
)
import trio

from libp2p.crypto.ed25519 import (
    create_new_key_pair,
)
from libp2p.host.basic_host import (
    BasicHost,
)
from libp2p.network.swarm import (
    Swarm,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerstore import (
    PeerStore,
)
from libp2p.security.noise.transport import (
    PROTOCOL_ID,
)
from libp2p.security.noise.transport import Transport as NoiseTransport
from libp2p.stream_muxer.mplex.mplex import (
    MPLEX_PROTOCOL_ID,
    Mplex,
)
from libp2p.transport.tcp.tcp import (
    TCP,
)
from libp2p.transport.upgrader import (
    TransportUpgrader,
)

from .webrtc import (
    WebRTCTransport,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc-loopback-test")


async def build_host(name: str) -> tuple[BasicHost, ID]:
    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    logger.info(f"Peer {name} ID: {peer_id}")

    base_transport = TCP()
    peer_store = PeerStore()
    secure_transports = {
        PROTOCOL_ID: NoiseTransport(libp2p_keypair=key_pair),
    }
    muxer_transports = {MPLEX_PROTOCOL_ID: Mplex}

    upgrader = TransportUpgrader(secure_transports, muxer_transports)
    swarm = Swarm(peer_id, peer_store, upgrader, base_transport)
    host = BasicHost(swarm)

    await host.get_network().listen(
        Multiaddr(f"/ip4/127.0.0.1/tcp/9095/ws/p2p/{peer_id}")
    )
    logger.info(f"Host {name} listening on: {host.get_network().listen(peer_id)}")
    return host, peer_id


async def run_loopback_test() -> None:
    host_b, peer_id_b = await build_host("webrtc")
    webrtc_b = WebRTCTransport(peer_id=peer_id_b, host=host_b)
    print(f"[*] Server Peer ID: {peer_id_b}")
    print(f"[*] Listening Addrs: {host_b.get_network().listen(peer_id_b)}")

    listener = await webrtc_b.create_listener(
        lambda conn: logger.info("[B] Listener ready")
    )

    async def act_as_server() -> None:
        conn = await listener.accept()
        msg = await conn.read()
        logger.info(f"[B] Got message: {msg.decode()}")
        await conn.write(b"Reply from B")

    async def act_as_client() -> None:
        host_a, peer_id_a = await build_host("webrtc")
        webrtc_a = WebRTCTransport(peer_id=peer_id_a, host=host_a)
        print(f"[*] Client Peer ID: {peer_id_a}")
        print(f"[*] Listening Addrs: {host_a.get_network().listening_addrs()}")

        conn = await webrtc_a.dial(
            Multiaddr(f"/ip4/127.0.0.1/tcp/9095/ws/p2p/{peer_id_b}/p2p-circuit/webrtc")
        )
        logger.info("[A] Dial successful")

        await conn.write(b"Hello from A")
        response = await conn.read()
        logger.info(f"[A] Got response: {response.decode()}")

    async with trio.open_nursery() as nursery:
        nursery.start_soon(act_as_server)
        await trio.sleep(1)
        nursery.start_soon(act_as_client)


if __name__ == "__main__":
    trio.run(run_loopback_test)
