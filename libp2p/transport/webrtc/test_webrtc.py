import trio
import pytest
from libp2p.tools.constants import LISTEN_MADDR
from .webrtc import WebRTCTransport
from libp2p import new_host
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from multiaddr import Multiaddr
from libp2p.abc import TProtocol
from multiaddr.protocols import (
    Protocol,
    add_protocol,
)
from .connection import WebRTCRawConnection
import logging
from libp2p.crypto.ed25519 import (
    create_new_key_pair,
)
from libp2p.host.basic_host import (
    IHost,
)
from libp2p.peer.id import (
    ID,
)
from .gen_certhash import CertificateManager, generate_webrtc_multiaddr

logger = logging.getLogger("test-webrtc")
logging.basicConfig(level=logging.INFO)
SIGNAL_PROTOCOL: TProtocol = TProtocol("/libp2p/webrtc/signal/1.0.0")

@pytest.mark.trio
async def test_webrtc_transport_end_to_end() -> None:
    async with trio.open_nursery() as nursery:
        Key_pair = create_new_key_pair()
        peer_id = ID.from_pubkey(Key_pair.public_key)
        print(f"Peer ID: {peer_id}")
        # Create Peer A
        host_a = new_host(key_pair=Key_pair)
        pubsub_a = Pubsub(
        host_a,
        GossipSub(protocols=[SIGNAL_PROTOCOL], degree=10, degree_low=3, degree_high=15),
        None,
    )
        transport_a = WebRTCTransport(host_a, pubsub_a)
        await transport_a.start()

        # Create Peer B
        host_b = new_host()
        pubsub_b = Pubsub(
        host_b,
        GossipSub(protocols=[SIGNAL_PROTOCOL], degree=10, degree_low=3, degree_high=15),
        None,
        )
        transport_b = WebRTCTransport(host_b, pubsub_b)
        await transport_b.start()

        list_addr= host_b.get_addrs()
        peer_id = host_b.get_id()
        # if "webrtc" not in Protocol.name :
        add_protocol(Protocol(name="webrtc", code=288, codec=None))
        add_protocol(Protocol(name="webrtc-direct", code= 289, codec= None))
        add_protocol(Protocol(name="certhash", code= 292, codec= None))
        add_protocol(Protocol(name="uEiBRYnd2NEs_2ycHGcld_M94-cKNOoLZamuSaGz_ArLaUA", code= 293, codec= None))
        maddr_b = Multiaddr(f"/ip4/0.0.0.0/tcp/0/ws/p2p/{host_b.get_id()}/p2p-circuit/webrtc")

        list_multiaddr= [
            Multiaddr(f"/ip4/127.0.0.1/udp/9095/webrtc/p2p/{peer_id}"),
            Multiaddr(f"/ip4/127.0.0.1/tcp/4001/ws/p2p/{peer_id}/p2p-circuit/webrtc"),
            Multiaddr(f"/ip4/127.0.0.1/tcp/4001/ws/p2p/{peer_id}/p2p-circuit/webrtc"),
            Multiaddr(f"/ip4/127.0.0.1/udp/9095/webrtc/p2p/{peer_id}"),
        ]

        # nursery.start_soon(host_a.run, [])
        # nursery.start_soon(host_b.run, [])
        host_a.run(listen_addrs=LISTEN_MADDR)
        host_b.run(listen_addrs=LISTEN_MADDR)
        # await trio.sleep(2)

        certhash = CertificateManager().get_certhash()
        print(f"Certificate PEM: {certhash}")
        signal_webrtc_maddr = generate_webrtc_multiaddr("192.168.0.1", str(peer_id), certhash="uEiBRYnd2NEs_2ycHGcld_M94-cKNOoLZamuSaGz_ArLaUA")
        signal_maddr = "/ip4/0.0.0.0/tcp/ws/0"
        print(f"Signal WebRTC Multiaddr: {signal_maddr}")
        print(f"Signal WebRTC Multiaddr: {signal_webrtc_maddr}")
    
        # conn = await transport_a.dial(maddr_b)
        conn: WebRTCRawConnection = await transport_a.dial(signal_maddr)

        # Check the channel is open
        assert conn is not None
        assert conn.channel.readyState == "open"

        logger.info("[Test] WebRTC channel open. Sending message...")

        # Send message
        test_msg = "Hello from A"
        conn.channel.send(test_msg)
        logger.info(f"[Test] Peer A sent: {test_msg}")

        # Listen on B
        received = trio.Event()
        def on_message(msg: str) -> None:
            if msg == test_msg:
                logger.info(f"[Test] Peer B received: {msg}")
                received.set()

        for ch in transport_b.connected_peers.values():
            if ch.readyState == "open":
                ch.on("message", on_message)

        conn.channel.send(test_msg)

        trio.fail_after(5)

        logger.info("[Test] Message exchange succeeded")
        await host_a.close()
        await host_b.close()
        nursery.cancel_scope.cancel()

