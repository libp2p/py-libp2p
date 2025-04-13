import json
import logging
from typing import (
    Any,
)

logger = logging.getLogger("signal-protocol")
PROTOCOL_ID = "/libp2p/webrtc/signal/1.0.0"


class WebRTCSignalingProtocol:
    def __init__(self, transport: Any):
        self.transport = transport

    async def handle_stream(self, stream: Any) -> None:
        """Handle incoming signaling messages on a libp2p stream"""
        try:
            while True:
                data = await stream.read()
                if not data:
                    break

                message = json.loads(data.decode())

                msg_type = message.get("type")
                if msg_type == "offer":
                    await self.transport.handle_offer_from_peer(stream, message)
                elif msg_type == "answer":
                    await self.transport.handle_answer_from_peer(message)
                elif msg_type == "ice":
                    await self.transport.handle_ice_candidate(message)
        except Exception as e:
            logger.error(f"Error handling signaling stream: {e}")
