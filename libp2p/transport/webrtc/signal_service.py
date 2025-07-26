from collections.abc import (
    Awaitable,
    Callable,
)
import json
import logging
from typing import (
    Any,
)

from aiortc import (
    RTCIceCandidate,
    RTCSessionDescription,
)
import trio

from libp2p.abc import (
    IHost,
    INetStream,
    INotifee,
    TProtocol,
)
from libp2p.peer.id import (
    ID,
)

from ..constants import SIGNALING_PROTOCOL

logger = logging.getLogger("libp2p.transport.webrtc.signal")


class SignalService(INotifee):
    """
    Handles SDP offer/answer exchange and ICE candidate signaling
    over libp2p streams for WebRTC connections.
    """

    def __init__(self, host: IHost) -> None:
        self.host = host
        self.signal_protocol = TProtocol(SIGNALING_PROTOCOL)
        self._handlers: dict[str, Callable[[dict[str, Any], str], Awaitable[None]]] = {}
        self._is_listening = False

        # Track active signaling streams
        self.active_streams: dict[str, INetStream] = {}
        # ICE candidate queue for trickling
        self.ice_candidate_queues: dict[str, list[dict[str, Any]]] = {}

    def set_handler(
        self, msg_type: str, handler: Callable[[dict[str, Any], str], Awaitable[None]]
    ) -> None:
        self._handlers[msg_type] = handler

    async def listen(self, network: Any, multiaddr: Any) -> None:
        self.host.set_stream_handler(self.signal_protocol, self.handle_signal)
        return None

    async def handle_signal(self, stream: INetStream) -> None:
        peer_id = stream.muxed_conn.peer_id
        reader = stream

        while True:
            try:
                data = await reader.read(4096)
                if not data:
                    break
                msg = json.loads(data.decode())
                msg_type = msg.get("type")
                if msg_type in self._handlers:
                    await self._handlers[msg_type](msg, str(peer_id))
                else:
                    print(f"No handler for msg type: {msg_type}")
            except Exception as e:
                print(f"Error in signal handler for {peer_id}: {e}")
                break

    async def send_signal(self, peer_id: ID, message: dict[str, Any]) -> None:
        """Send a signaling message to a peer"""
        try:
            peer_id_str = str(peer_id)

            # Use existing stream if available, otherwise create new one
            if peer_id_str in self.active_streams:
                stream = self.active_streams[peer_id_str]
            else:
                stream = await self.host.new_stream(peer_id, [self.signal_protocol])
                self.active_streams[peer_id_str] = stream

            message_data = json.dumps(message).encode()
            await stream.write(message_data)
            logger.debug(f"Sent signal message to {peer_id}: {message['type']}")

        except Exception as e:
            logger.error(f"Failed to send signal to {peer_id}: {e}")
            # Clean up failed stream
            if peer_id_str in self.active_streams:
                del self.active_streams[peer_id_str]
            raise

    async def send_offer(
        self, peer_id: ID, sdp: str, sdp_type: str, certhash: str
    ) -> None:
        await self.send_signal(
            peer_id,
            {"type": "offer", "sdp": sdp, "sdpType": sdp_type, "certhash": certhash},
        )

    async def send_answer(
        self, peer_id: ID, sdp: str, sdp_type: str, certhash: str
    ) -> None:
        await self.send_signal(
            peer_id,
            {"type": "answer", "sdp": sdp, "sdpType": sdp_type, "certhash": certhash},
        )

    async def send_ice_candidate(self, peer_id: ID, candidate: RTCIceCandidate) -> None:
        """Send ICE candidate with trickling support"""
        peer_id_str = str(peer_id)
        candidate_msg = {
            "type": "ice",
            "candidateType": candidate.type,
            "component": candidate.component,
            "foundation": candidate.foundation,
            "priority": candidate.priority,
            "ip": candidate.ip,
            "port": candidate.port,
            "protocol": candidate.protocol,
            "sdpMid": candidate.sdpMid,
        }

        # Queue candidate if stream not ready
        if peer_id_str not in self.active_streams:
            if peer_id_str not in self.ice_candidate_queues:
                self.ice_candidate_queues[peer_id_str] = []
            self.ice_candidate_queues[peer_id_str].append(candidate_msg)
            logger.debug(f"Queued ICE candidate for {peer_id}")
            return

        await self.send_signal(peer_id, candidate_msg)

    async def flush_ice_candidates(self, peer_id: ID) -> None:
        """Flush queued ICE candidates after signaling stream is established"""
        peer_id_str = str(peer_id)
        if peer_id_str in self.ice_candidate_queues:
            candidates = self.ice_candidate_queues.pop(peer_id_str)
            for candidate_msg in candidates:
                await self.send_signal(peer_id, candidate_msg)
            logger.debug(f"Flushed {len(candidates)} ICE candidates for {peer_id}")

    async def send_connection_state(
        self, peer_id: ID, state: str, reason: str | None = None
    ) -> None:
        """Send connection state update"""
        message = {"type": "connection_state", "state": state}
        if reason:
            message["reason"] = reason
        await self.send_signal(peer_id, message)

    async def negotiate_connection(
        self, peer_id: ID, offer: RTCSessionDescription, certhash: str
    ) -> RTCSessionDescription:
        """Complete SDP offer/answer exchange with error handling and timeouts"""
        try:
            # Send offer
            await self.send_offer(peer_id, offer.sdp, offer.type, certhash)

            # Wait for answer with timeout
            answer_received = trio.Event()
            received_answer = None
            error_occurred = None

            async def answer_handler(msg: dict[str, Any], sender_peer_id: str) -> None:
                nonlocal received_answer, error_occurred
                if sender_peer_id == str(peer_id):
                    if msg.get("type") == "answer":
                        try:
                            received_answer = RTCSessionDescription(
                                sdp=msg["sdp"], type=msg["sdpType"]
                            )
                            answer_received.set()
                        except Exception as e:
                            error_occurred = f"Invalid answer format: {e}"
                            answer_received.set()
                    elif msg.get("type") == "error":
                        error_occurred = msg.get("message", "Unknown error")
                        answer_received.set()

            # Set temporary handler for answer
            self.set_handler("answer", answer_handler)
            self.set_handler("error", answer_handler)

            # Wait for answer with timeout
            with trio.move_on_after(30.0) as cancel_scope:
                await answer_received.wait()

            if cancel_scope.cancelled_caught:
                raise TimeoutError("SDP answer exchange timed out")

            if error_occurred:
                raise ConnectionError(f"SDP negotiation failed: {error_occurred}")

            if not received_answer:
                raise ConnectionError("No valid answer received")

            # Flush any queued ICE candidates
            await self.flush_ice_candidates(peer_id)

            return received_answer

        except Exception as e:
            logger.error(f"SDP negotiation failed with {peer_id}: {e}")
            await self.send_connection_state(peer_id, "failed", str(e))
            raise

    async def handle_incoming_connection(
        self, offer: RTCSessionDescription, sender_peer_id: str, certhash: str
    ) -> RTCSessionDescription:
        """Handle incoming connection offer and generate answer"""
        try:
            # TODO: Return answer SDP after setting up peer connection
            raise NotImplementedError(
                "Handle incoming connection must be implemented by transport"
            )

        except Exception as e:
            logger.error(
                f"Failed to handle incoming connection from {sender_peer_id}: {e}"
            )
            error_msg: dict[str, Any] = {"type": "error", "message": str(e)}
            await self.send_signal(ID(sender_peer_id.encode()), error_msg)
            raise

    async def close_stream(self, peer_id: ID) -> None:
        """Close signaling stream and clean up resources"""
        peer_id_str = str(peer_id)

        if peer_id_str in self.active_streams:
            try:
                stream = self.active_streams.pop(peer_id_str)
                await stream.close()
                logger.debug(f"Closed signaling stream to {peer_id}")
            except Exception as e:
                logger.warning(f"Error closing stream to {peer_id}: {e}")

        if peer_id_str in self.ice_candidate_queues:
            del self.ice_candidate_queues[peer_id_str]

    async def connected(self, network: Any, conn: Any) -> None:
        pass

    async def disconnected(self, network: Any, conn: Any) -> None:
        pass

    async def opened_stream(self, network: Any, stream: Any) -> None:
        pass

    async def closed_stream(self, network: Any, stream: Any) -> None:
        pass

    async def listen_close(self, network: Any, multiaddr: Any) -> None:
        pass
