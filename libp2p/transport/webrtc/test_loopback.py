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

from libp2p import (
    new_host,
)
from libp2p.crypto.ed25519 import (
    create_new_key_pair,
)
from libp2p.host.basic_host import (
    IHost,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.peer.peerstore import (
    PeerInfo,
)
from libp2p.pubsub.gossipsub import (
    GossipSub,
)
from libp2p.pubsub.pubsub import (
    Pubsub,
)

from .connection import (
    WebRTCRawConnection,
)
from .gen_certhash import (
    filter_addresses,
)
from .webrtc import (
    SIGNAL_PROTOCOL,
    WebRTCTransport,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc-loopback-test")


async def build_host(name: str) -> tuple[IHost, ID, WebRTCTransport]:
    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    key_pair.private_key
    key_pair.public_key
    logger.info(f"[{name}] Peer ID: {peer_id}")

    host = new_host()
    pubsub = Pubsub(
        host,
        GossipSub(protocols=[SIGNAL_PROTOCOL], degree=10, degree_low=3, degree_high=15),
        None,
    )
    webrtc_transport = WebRTCTransport(host, pubsub)

    return host, peer_id, webrtc_transport


async def run_loopback_test(nursery: Nursery) -> None:
    host_b, peer_id_b, webrtc_transport_b = await build_host("Server")
    logger.info(f"[B] Peer ID: {peer_id_b}")
    addrs = host_b.get_addrs()
    PeerInfo(peer_id_b, addrs)
    listen = host_b.run(addrs)
    logger.info(f"[B] Listening Addrs: {addrs} --- {listen}")
    logger.info(f"[B] Active Addrs: {host_b.get_live_peers()}")
    webrtc_proto = Protocol(name="webrtc", code=277, codec=None)
    add_protocol(webrtc_proto)
    # webrtc_conn = await webrtc_transport_b.create_listener(handler_func=)

    # await webrtc_conn.listen(
    #     Multiaddr(f"/ip4/127.0.0.1/tcp/9095/ws/p2p/{peer_id_b}/p2p-circuit/webrtc"),
    #     nursery,
    # )

    logger.info("[B] Listening WebRTC setup complete.")

    async def act_as_server() -> None:
        try:
            logger.info("[B] Waiting to accept connection...")
            active_maddr = host_b.get_addrs()
            info = info_from_p2p_addr(active_maddr[0])
            conn = host_b.connect(info)
            logger.info(f"[B] Connection accepted. {conn}")

            stream = await host_b.new_stream(peer_id_b, [SIGNAL_PROTOCOL])
            offer_data = await stream.read()
            offer_json = json.loads(offer_data.decode())

            await webrtc_transport_b._handle_signal_message(peer_id_b, offer_json)
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
        pc = webrtc_client._create_peer_connection()
        await webrtc_client.create_data_channel(pc)

        valid = [
            Multiaddr(f"/ip4/127.0.0.1/udp/9095/webrtc/p2p/{peer_id_a}"),
            Multiaddr(f"/ip4/127.0.0.1/tcp/4001/ws/p2p/{peer_id_a}/p2p-circuit/webrtc"),
            Multiaddr(f"/ip4/127.0.0.1/tcp/4001/ws/p2p/{peer_id_b}/p2p-circuit/webrtc"),
            Multiaddr(f"/ip4/127.0.0.1/udp/9095/webrtc/p2p/{peer_id_b}"),
        ]

        maddr = filter_addresses(valid)
        host_a.get_network().peerstore.add_addr(peer_id_a, maddr, 3000)
        logger.info(f"[A] Peerstore updated with address: {maddr}")

        stream = await host_a.new_stream(peer_id_a, [SIGNAL_PROTOCOL])

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
            conn = WebRTCRawConnection(peer_id_a, webrtc_client.data_channel)
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
