import json
import logging

from multiaddr import (
    Multiaddr,
)
from multiaddr.protocols import (
    Protocol,
    add_protocol,
)
import trio
from trio import (
    Nursery,
)

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
from libp2p.transport.upgrader import (
    TransportUpgrader,
)

from .connection import (
    WebRTCRawConnection,
)
from .listener import (
    WebRTCListener,
)
from .webrtc import (
    SIGNAL_PROTOCOL,
    WebRTCTransport,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc-loopback-test")


async def build_host(name: str) -> tuple[BasicHost, ID, WebRTCTransport]:
    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    logger.info(f"[{name}] Peer ID: {peer_id}")

    webrtc_transport = WebRTCTransport(peer_id=peer_id, host=None)
    peer_store = PeerStore()

    secure_transports = {PROTOCOL_ID: NoiseTransport(libp2p_keypair=key_pair)}
    muxer_transports = {MPLEX_PROTOCOL_ID: Mplex}
    upgrader = TransportUpgrader(secure_transports, muxer_transports)

    swarm = Swarm(peer_id, peer_store, upgrader, webrtc_transport)
    host = BasicHost(swarm)
    webrtc_transport.host = host

    return host, peer_id, webrtc_transport


async def run_loopback_test(nursery: Nursery) -> None:
    host_b, peer_id_b, webrtc_transport_b = await build_host("Server")
    logger.info(f"[B] Peer ID: {peer_id_b}")
    logger.info(f"[B] Listening Addrs: {host_b.get_connected_peers()}")
    webrtc_proto = Protocol(name="webrtc", code=277, codec=None)
    add_protocol(webrtc_proto)
    webrtc_conn = webrtc_transport_b.create_listener(WebRTCListener)

    # await webrtc_listener.listen(
    #     Multiaddr(f"/ip4/127.0.0.1/tcp/9095/ws/p2p/{peer_id_b}/p2p-circuit/webrtc"),
    #     nursery,
    # )

    # for addr in webrtc_listener.:
    #     logger.info(f"[B] Listening on: {addr}")

    logger.info("[B] Listening WebRTC setup complete.")

    async def act_as_server() -> None:
        try:
            logger.info("[B] Waiting to accept connection...")
            conn: WebRTCRawConnection = await webrtc_conn
            logger.info("[B] Connection accepted.")

            stream = await host_b.new_stream(conn.peer_id, [SIGNAL_PROTOCOL])
            offer_data = await stream.read()
            offer_json = json.loads(offer_data.decode())

            await webrtc_transport_b.handle_offer_from_peer(stream, offer_json)
            answer = await webrtc_transport_b.peer_connection.createAnswer()
            await webrtc_transport_b.peer_connection.setLocalDescription(answer)

            await stream.write(
                json.dumps({"sdp": answer.sdp, "sdpType": answer.type}).encode()
            )

            await trio.sleep(1)

            if webrtc_transport_b.data_channel is not None:
                raw_conn = WebRTCRawConnection(
                    peer_id_b, webrtc_transport_b.data_channel
                )
                msg = await raw_conn.read()
                logger.info(f"[B] Received: {msg.decode()}")
                await raw_conn.write(b"Reply from B")
                await raw_conn.close()
            else:
                logger.error("[B] Data channel not established!")
        except Exception as e:
            logger.error(f"[B] Error in act_as_server: {e}")

    async def act_as_client() -> None:
        host_a, peer_id_a, webrtc_client = await build_host("Client")
        await webrtc_client.create_data_channel()

        maddr = Multiaddr(
            f"/ip4/127.0.0.1/tcp/4001/ws/p2p/{peer_id_b}/p2p-circuit/webrtc"
        )
        host_a.get_network().peerstore.add_addr(peer_id_b, maddr, 3000)
        logger.info(f"[A] Peerstore updated with address: {maddr}")

        stream = await host_a.new_stream(peer_id_b, [SIGNAL_PROTOCOL])

        offer = await webrtc_client.peer_connection.createOffer()
        await webrtc_client.peer_connection.setLocalDescription(offer)
        await stream.write(
            json.dumps({"sdp": offer.sdp, "sdpType": offer.type}).encode()
        )

        answer_data = await stream.read()
        answer_json = json.loads(answer_data.decode())
        await webrtc_client.handle_answer_from_peer(answer_json)

        await trio.sleep(1)

        if webrtc_client.data_channel is not None:
            conn = WebRTCRawConnection(peer_id_b, webrtc_client.data_channel)
            await conn.write(b"Hello from A")
            reply = await conn.read()
            logger.info(f"[A] Received: {reply.decode()}")
            await conn.close()
        else:
            logger.error("[A] Data channel not established!")

    async with trio.open_nursery() as nursery:
        nursery.start_soon(act_as_server)
        await trio.sleep(1.5)
        nursery.start_soon(act_as_client)


async def run_loopback_main() -> None:
    async with trio.open_nursery() as nursery:
        await run_loopback_test(nursery)


if __name__ == "__main__":
    trio.run(lambda: run_loopback_main())
