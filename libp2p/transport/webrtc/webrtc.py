from collections.abc import (
    Coroutine,
)
import json
import logging
from typing import (
    Any,
    Callable,
    Optional,
)

from aiortc import (
    RTCDataChannel,
    RTCIceCandidate,
    RTCPeerConnection,
    RTCSessionDescription,
)
from multiaddr import (
    Multiaddr,
)
import trio

from libp2p.abc import (
    IListener,
    IRawConnection,
    ITransport,
)
from libp2p.host.basic_host import (
    BasicHost,
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

logger = logging.getLogger("webrtc")
logging.basicConfig(level=logging.INFO)
SIGNAL_PROTOCOL = "/libp2p/webrtc/signal/1.0.0"


class WebRTCRawConnection(IRawConnection):
    def __init__(self, channel: RTCDataChannel):
        self.channel = channel
        self.receive_channel, self.send_channel = trio.open_memory_channel(0)

        @channel.on("message")
        def on_message(message: Any) -> None:
            self.send_channel.send_nowait(message)

    async def read(self, n: int = -1) -> bytes:
        return await self.receive_channel.receive()

    async def write(self, data: bytes) -> None:
        self.channel.send(data)

    async def close(self) -> None:
        self.channel.close()


class WebRTCListener(IListener):
    def __init__(self, host, peer_id: ID):
        self.host = host
        self.peer_id = peer_id
        self.conn_send_channel, self.conn_recv_channel = trio.open_memory_channel(0)

    async def listen(self, maddr: Multiaddr) -> None:
        await self.host.set_stream_handler(SIGNAL_PROTOCOL, self._handle_stream)

    async def accept(self) -> IRawConnection:
        return await self.conn_recv_channel.receive()

    async def close(self) -> None:
        pass

    async def _handle_stream(self, stream) -> None:
        pc = RTCPeerConnection()
        channel_ready = trio.Event()

        @pc.on("datachannel")
        def on_datachannel(channel: RTCDataChannel) -> None:
            @channel.on("open")
            def opened():
                channel_ready.set()

            self.conn_send_channel.send_nowait(WebRTCRawConnection(channel))

        offer_data = await stream.read()
        offer_msg = json.loads(offer_data.decode())
        offer = RTCSessionDescription(**offer_msg)
        await pc.setRemoteDescription(offer)

        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        await stream.write(
            json.dumps({"sdp": answer.sdp, "type": answer.type}).encode()
        )

        await channel_ready.wait()


class WebRTCTransport(ITransport):
    def __init__(self, peer_id, host: BasicHost, config: Optional[dict] = None):
        self.peer_id = peer_id
        self.host = host
        self.config = config or {}
        self.peer_connection = RTCPeerConnection()
        self.data_channel: Optional[RTCDataChannel] = None
        self.pubsub: Optional[Pubsub] = None

    async def create_data_channel(self) -> None:
        """Creates and opens a WebRTC data channel"""
        self.data_channel = self.peer_connection.createDataChannel("libp2p-webrtc")

        @self.data_channel.on("open")
        def on_open() -> None:
            logger.info(f"Data channel open with peer {self.peer_id}")

        @self.data_channel.on("message")
        def on_message(message: Any) -> None:
            logger.info(f"Received message from peer {self.peer_id}: {message}")

    async def handle_offer_from_peer(self, stream: Any, data: dict) -> None:
        """Handle offer and send back answer on same stream"""
        offer = RTCSessionDescription(sdp=data["sdp"], type=data["sdpType"])
        await self.peer_connection.setRemoteDescription(offer)

        answer = await self.peer_connection.createAnswer()
        await self.peer_connection.setLocalDescription(answer)

        response = {
            "type": "answer",
            "sdp": answer.sdp,
            "sdpType": answer.type,
            "peer_id": self.peer_id,
        }

        await stream.write(json.dumps(response).encode())

    async def handle_answer_from_peer(self, data: dict) -> None:
        """Handle SDP answer from peer"""
        answer = RTCSessionDescription(sdp=data["sdp"], type=data["sdpType"])
        await self.peer_connection.setRemoteDescription(answer)

    async def handle_ice_candidate(self, data: dict) -> None:
        """Optional: ICE candidate support"""
        candidate = RTCIceCandidate(
            component=data["component"],
            foundation=data["foundation"],
            priority=data["priority"],
            ip=data["ip"],
            protocol=data["protocol"],
            port=data["port"],
            type=data["candidateType"],
        )
        await self.peer_connection.addIceCandidate(candidate)

    async def start_peer_discovery(self) -> None:
        """Starts peer discovery using GossipSub"""
        gossipsub = GossipSub()
        self.pubsub = Pubsub(self.host, gossipsub, None)

        topic = await self.pubsub.subscribe("webrtc-peer-discovery")

        async def handle_message() -> None:
            async for msg in topic:
                logger.info(f"Discovered Peer: {msg.data.decode()}")

        async with trio.open_nursery() as nursery:
            nursery.start_soon(handle_message)

        await self.pubsub.publish("webrtc-peer-discovery", self.peer_id.encode())

    async def create_listener(
        self, handler: Callable[[IRawConnection], Coroutine[Any, Any, None]]
    ) -> IListener:
        listener = WebRTCListener(self.host, self.peer_id)
        await listener.listen(
            Multiaddr(
                f"/ip4/147.28.186.157/tcp/9095/p2p/12D3KooWFhXabKDwALpzqMbto94sB7rvmZ6M28hs9Y9xSopDKwQr/p2p-circuit/webrtc"
            )
        )
        self.host.set_stream_handler(SIGNAL_PROTOCOL, listener._handle_stream)
        return listener

    async def dial(self, maddr: Multiaddr) -> IRawConnection:
        peer_id = parse_webrtc_multiaddr(maddr)
        stream = await self.host.new_stream(peer_id, [SIGNAL_PROTOCOL])

        pc = RTCPeerConnection()
        channel = pc.createDataChannel("libp2p")

        channel_ready = trio.Event()

        @channel.on("open")
        def on_open() -> None:
            channel_ready.set()

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        await stream.write(
            json.dumps(
                {
                    "type": "offer",
                    "peer_id": self.peer_id,
                    "sdp": offer.sdp,
                    "sdpType": offer.type,
                }
            ).encode()
        )

        answer_data = await stream.read()
        answer_msg = json.loads(answer_data.decode())
        answer = RTCSessionDescription(**answer_msg)
        await pc.setRemoteDescription(answer)

        await channel_ready.wait()

        return WebRTCRawConnection(channel)


def parse_webrtc_multiaddr(multiaddr_str: str) -> Multiaddr:
    """Parse and validate a WebRTC multiaddr."""
    try:
        addr = Multiaddr(multiaddr_str)
        if "/webrtc" not in [p.name for p in addr.protocols()]:
            raise ValueError("Invalid WebRTC multiaddr: Missing /webrtc protocol")
        return addr
    except Exception as e:
        logger.error(f"Failed to parse multiaddr: {e}")
        return None
