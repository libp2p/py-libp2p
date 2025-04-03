import asyncio
import json
import websockets
import logging
from aiortc import RTCIceCandidate, RTCPeerConnection, RTCSessionDescription, RTCDataChannel
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.host.basic_host import BasicHost
from multiaddr import Multiaddr

SIGNALING_SERVER_URL = "ws://localhost:8765"

# Initialize logger
logger = logging.getLogger("webrtc-transport")
logging.basicConfig(level=logging.INFO)

class WebRTCTransport:
    def __init__(self, peer_id, host: BasicHost):
        self.peer_id = peer_id
        self.host = host
        self.peer_connection = RTCPeerConnection()
        self.data_channel = None
        self.pubsub = None
        self.websocket = None

    async def connect_signaling_server(self):
        """Connects to the WebSocket-based signaling server"""
        try:
            self.websocket = await websockets.connect(SIGNALING_SERVER_URL)
            await self.websocket.send(json.dumps({"type": "register", "peer_id": self.peer_id}))
            asyncio.create_task(self.listen_signaling())
        except Exception as e:
            logger.error(f"Failed to connect to signaling server: {e}")

    async def listen_signaling(self):
        """Listens for incoming SDP offers and answers"""
        try:
            async for message in self.websocket:
                data = json.loads(message)
                if data["type"] == "offer":
                    await self.handle_offer(data)
                elif data["type"] == "answer":
                    await self.handle_answer(data)
        except Exception as e:
            logger.error(f"Error in signaling listener: {e}")

    async def handle_offer(self, data):
        """Handles incoming SDP offers"""
        offer = RTCSessionDescription(sdp=data["sdp"], type=data["type"])
        await self.peer_connection.setRemoteDescription(offer)

        # Create an answer
        answer = await self.peer_connection.createAnswer()
        await self.peer_connection.setLocalDescription(answer)

        await self.websocket.send(json.dumps({
            "type": "answer",
            "target": data["peer_id"],
            "sdp": answer.sdp
        }))

    async def handle_answer(self, data):
        """Handles incoming SDP answers"""
        answer = RTCSessionDescription(sdp=data["sdp"], type=data["type"])
        await self.peer_connection.setRemoteDescription(answer)

    async def create_data_channel(self):
        """Creates and opens a WebRTC data channel"""
        self.data_channel = self.peer_connection.createDataChannel("libp2p-webrtc")

        @self.data_channel.on("open")
        def on_open():
            logger.info(f"Data channel open with peer {self.peer_id}")

        @self.data_channel.on("message")
        def on_message(message):
            logger.info(f"Received message from peer {self.peer_id}: {message}")

    async def initiate_connection(self, target_peer_id):
        """Initiates connection with a peer"""
        self.data_channel = self.peer_connection.createDataChannel("libp2p-webrtc")

        offer = await self.peer_connection.createOffer()
        await self.peer_connection.setLocalDescription(offer)

        await self.websocket.send(json.dumps({
            "type": "offer",
            "peer_id": self.peer_id,
            "target": target_peer_id,
            "sdp": offer.sdp
        }))

    async def start_peer_discovery(self):
        """Starts peer discovery using GossipSub"""
        gossipsub = GossipSub()
        self.pubsub = Pubsub(self.host, gossipsub, None)

        topic = await self.pubsub.subscribe("webrtc-peer-discovery")

        async def handle_message():
            async for msg in topic:
                logger.info(f"Discovered Peer: {msg.data.decode()}")

        asyncio.create_task(handle_message())

        # Advertise this peer
        await self.pubsub.publish("webrtc-peer-discovery", self.peer_id.encode())

# Multiaddr Parsing & Validation
def parse_webrtc_multiaddr(multiaddr_str):
    """Parse and validate a WebRTC multiaddr."""
    try:
        addr = Multiaddr(multiaddr_str)
        if "/webrtc" not in [p.name for p in addr.protocols()]:
            raise ValueError("Invalid WebRTC multiaddr: Missing /webrtc protocol")
        return addr
    except Exception as e:
        logger.error(f"Failed to parse multiaddr: {e}")
        return None
