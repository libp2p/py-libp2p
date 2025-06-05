import logging

import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.ed25519 import (
    create_new_key_pair,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.pubsub.gossipsub import (
    GossipSub,
)
from libp2p.pubsub.pubsub import (
    Pubsub,
)

from .gen_certhash import (
    CertificateManager,
    create_webrtc_direct_multiaddr,
)
from .webrtc import (
    WebRTCTransport,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc-direct-loopback-test")


async def build_host_and_transport(name: str):
    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    logger.info(f"[{name}] Peer ID: {peer_id}")

    host = new_host()
    pubsub = Pubsub(
        host,
        GossipSub(
            protocols=["/libp2p/webrtc/signal/1.0.0"],
            degree=10,
            degree_low=3,
            degree_high=15,
        ),
        None,
    )
    webrtc_transport = WebRTCTransport(host, pubsub)
    return host, peer_id, webrtc_transport


async def run_webrtc_direct_loopback_test():
    # Server (listener)
    host_b, peer_id_b, webrtc_transport_b = await build_host_and_transport("Server")
    cert_mgr_b = CertificateManager()
    cert_mgr_b.generate_self_signed_cert()

    maddr_b = create_webrtc_direct_multiaddr(
        ip="127.0.0.1", port=9000, peer_id=peer_id_b
    )
    logger.info(f"[B] Listening on: {maddr_b}")

    listener = await webrtc_transport_b.create_listener()
    listener.set_host(host_b)
    await listener.listen(maddr_b)
    listener_maddr = listener.get_addrs()
    logger.info(f"[B] Listener Multiaddr: {listener_maddr}")

    # Client (dialer)
    host_a, peer_id_a, webrtc_transport_a = await build_host_and_transport("Client")
    cert_mgr_a = CertificateManager()
    cert_mgr_a.generate_self_signed_cert()

    async def server_logic():
        try:
            logger.info("[B] Waiting for incoming WebRTC-Direct connection...")
            raw_conn = await listener.accept()
            logger.info("[B] WebRTC-Direct connection accepted")

            # Testing bidirectional communication
            msg = await raw_conn.read()
            logger.info(f"[B] Received: {msg.decode()}")
            await raw_conn.write(b"Reply from B (webrtc-direct)")

            # Testing stream handling
            stream = await raw_conn.open_stream()
            await stream.write(b"Stream test from B")
            stream_data = await stream.read()
            logger.info(f"[B] Stream data received: {stream_data.decode()}")

            await raw_conn.close()
            logger.info("[B] Connection closed")
        except Exception as e:
            logger.error(f"[B] Error in server_logic: {e}")
            raise

    async def client_logic():
        try:
            await trio.sleep(1.0)
            logger.info("[A] Dialing WebRTC-Direct...")

            with trio.move_on_after(60) as cancel_scope:  # Add timeout
                conn = await webrtc_transport_a.webrtc_direct_dial(maddr_b)

            if cancel_scope.cancelled_caught:
                logger.error("[A] Connection attempt timed out")
                return

            logger.info("[A] WebRTC-Direct connection established.")
            await conn.write(b"Hello from A (webrtc-direct)")
            reply = await conn.read()
            logger.info(f"[A] Received: {reply.decode()}")
            await conn.close()

            # Test stream handling
            # stream = await conn.open_stream()
            # await stream.write(b"Stream test from A")
            # stream_data = await stream.read()
            # logger.info(f"[A] Stream data received: {stream_data.decode()}")

            # await conn.close()
            logger.info("[A] Connection closed")
        except Exception as e:
            logger.error(f"[A] Error in client_logic: {e}")
            raise

    async with trio.open_nursery() as nursery:
        nursery.start_soon(server_logic)
        nursery.start_soon(client_logic)


async def run_main():
    await run_webrtc_direct_loopback_test()


if __name__ == "__main__":
    trio.run(run_main)
