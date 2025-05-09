import json
import logging
from typing import (
    Any,
    Callable,
    Optional,
)

from _collections_abc import (
    Coroutine,
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
    ISecureConn,
    ITransport,
    TProtocol,
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

from .connection import (
    WebRTCRawConnection,
)
from .listener import (
    WebRTCListener,
)
from .utils import (
    parse_webrtc_multiaddr,
)

logger = logging.getLogger("webrtc")
logging.basicConfig(level=logging.INFO)
SIGNAL_PROTOCOL: TProtocol = TProtocol("/libp2p/webrtc/signal/1.0.0")


class WebRTCTransport(ITransport):
    def __init__(
        self, peer_id: ID, host: BasicHost, config: Optional[dict[str, Any]] = None
    ):
        self.peer_id = peer_id
        self.host = host
        self.config = config or {}
        self.peer_connection = RTCPeerConnection()
        self.data_channel: Optional[RTCDataChannel] = None
        self.pubsub: Optional[Pubsub] = None

    async def create_data_channel(self) -> None:
        self.data_channel = self.peer_connection.createDataChannel("libp2p-webrtc")

        @self.data_channel.on("open")
        def on_open() -> None:
            logger.info(f"Data channel open with peer {self.peer_id}")

        @self.data_channel.on("message")
        def on_message(message: Any) -> None:
            logger.info(f"Received message from peer {self.peer_id}: {message}")

    async def handle_offer_from_peer(self, stream: Any, data: dict[str, Any]) -> None:
        offer = RTCSessionDescription(sdp=data["sdp"], type=data["sdpType"])
        await self.peer_connection.setRemoteDescription(offer)

        answer = await self.peer_connection.createAnswer()
        await self.peer_connection.setLocalDescription(answer)

        response: dict[str, Any] = {
            "type": "answer",
            "sdp": answer.sdp,
            "sdpType": answer.type,
            "peer_id": str(self.peer_id),
        }

        await stream.write(json.dumps(response).encode())

    async def handle_answer_from_peer(self, data: dict[str, Any]) -> None:
        answer = RTCSessionDescription(sdp=data["sdp"], type=data["sdpType"])
        await self.peer_connection.setRemoteDescription(answer)

    async def handle_ice_candidate(self, data: dict[str, Any]) -> None:
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

    async def handle_incoming_candidates(
        self, stream: Any, peer_connection: RTCPeerConnection
    ) -> None:
        while True:
            try:
                raw = await stream.read()
                data: dict[str, Any] = json.loads(raw.decode())
                if data.get("type") == "ice":
                    candidate = RTCIceCandidate(
                        component=data["component"],
                        foundation=data["foundation"],
                        priority=data["priority"],
                        ip=data["ip"],
                        protocol=data["protocol"],
                        port=data["port"],
                        type=data["candidateType"],
                    )
                    await peer_connection.addIceCandidate(candidate)
            except Exception as e:
                logger.error(f"[ICE Trickling] Error reading ICE candidate: {e}")
                break

    async def start_peer_discovery(self) -> None:
        gossipsub = GossipSub(protocols=[], degree=10, degree_low=3, degree_high=15)
        self.pubsub = Pubsub(self.host, gossipsub, None)

        topic = await self.pubsub.subscribe("webrtc-peer-discovery")

        async def handle_message() -> None:
            async for msg in topic:
                logger.info(f"Discovered Peer: {msg.data.decode()}")

        async with trio.open_nursery() as nursery:
            nursery.start_soon(handle_message)

        await self.pubsub.publish("webrtc-peer-discovery", str(self.peer_id).encode())

    async def dial(self, maddr: Multiaddr) -> ISecureConn:
        peer_id = parse_webrtc_multiaddr(maddr)
        stream = await self.host.new_stream(peer_id, [SIGNAL_PROTOCOL])

        pc = RTCPeerConnection()

        @pc.on("icecandidate")
        def on_ice_candidate(candidate: Optional[RTCIceCandidate]) -> None:
            if candidate:
                msg = {
                    "type": "ice",
                    "candidateType": candidate.type,
                    "component": candidate.component,
                    "foundation": candidate.foundation,
                    "priority": candidate.priority,
                    "port": candidate.port,
                    "protocol": candidate.protocol,
                }
                trio.lowlevel.spawn_system_task(stream.write, json.dumps(msg).encode())

        trio.lowlevel.spawn_system_task(self.handle_incoming_candidates, stream, pc)

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
                    "peer_id": str(self.peer_id),
                    "sdp": offer.sdp,
                    "sdpType": offer.type,
                }
            ).encode()
        )

        answer_data = await stream.read()
        answer_msg: dict[str, Any] = json.loads(answer_data.decode())
        answer = RTCSessionDescription(**answer_msg)
        await pc.setRemoteDescription(answer)

        await channel_ready.wait()
        return WebRTCRawConnection(self.peer_id, channel)

    async def create_listener(
        self, handler: Callable[[WebRTCListener], Coroutine[Any, Any, None]]
    ) -> IListener:
        listener = await self.create_listener(handler=handler)
        return listener
