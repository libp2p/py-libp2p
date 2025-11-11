from collections import defaultdict
from collections.abc import Awaitable, Callable
import json
import logging
from typing import Any, cast

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

from .constants import SIGNALING_PROTOCOL

logger = logging.getLogger("libp2p.transport.webrtc.signal")


class SignalService(INotifee):
    """
    Handles SDP offer/answer exchange and ICE candidate signaling
    over libp2p streams for WebRTC connections.
    """

    def __init__(self, host: IHost) -> None:
        self.host = host
        self.signal_protocol = TProtocol(SIGNALING_PROTOCOL)
        self._handlers: dict[
            str, list[Callable[[dict[str, Any], str], Awaitable[Any]]]
        ] = defaultdict(list)
        self._is_listening = False

        # Track active signaling streams
        self.active_streams: dict[str, INetStream] = {}
        # ICE candidate queue for trickling
        self.ice_candidate_queues: dict[str, list[dict[str, Any]]] = {}
        # Local ICE candidates gathered before signaling stream is ready
        self.pending_local_ice: dict[
            str, list[tuple[dict[str, Any] | None, dict[str, Any] | None]]
        ] = {}

    def set_handler(
        self,
        msg_type: str,
        handler: Callable[[dict[str, Any], str], Awaitable[None]] | None,
    ) -> None:
        if handler is None:
            self._handlers.pop(msg_type, None)
        else:
            self._handlers[msg_type] = [handler]

    def add_handler(
        self,
        msg_type: str,
        handler: Callable[[dict[str, Any], str], Awaitable[None]],
    ) -> None:
        self._handlers[msg_type].append(handler)

    def remove_handler(
        self,
        msg_type: str,
        handler: Callable[[dict[str, Any], str], Awaitable[None]],
    ) -> None:
        handlers = self._handlers.get(msg_type)
        if not handlers:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            return
        if not handlers:
            self._handlers.pop(msg_type, None)

    async def listen(self, network: Any, multiaddr: Any) -> None:
        self.host.set_stream_handler(self.signal_protocol, self.handle_signal)
        if hasattr(network, "register_notifee"):
            try:
                network.register_notifee(self)
            except Exception:
                logger.debug(
                    "Failed to register signal service as notifee", exc_info=True
                )
        self._is_listening = True
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
                handlers = self._handlers.get(msg_type, [])
                if handlers:
                    for handler in list(handlers):
                        try:
                            await handler(msg, str(peer_id))
                        except Exception:
                            logger.exception(
                                "Signal handler for %s raised an exception", msg_type
                            )
                else:
                    logger.debug("No handler for signal message type %s", msg_type)
            except Exception as e:
                logger.error("Error in signal handler for %s: %s", peer_id, e)
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
            self.active_streams.pop(peer_id_str, None)
            raise

    async def send_offer(
        self,
        peer_id: ID,
        sdp: str,
        sdp_type: str,
        certhash: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "type": "offer",
            "sdp": sdp,
            "sdpType": sdp_type,
            "certhash": certhash,
        }
        if extra:
            payload.update(extra)
        await self.send_signal(
            peer_id,
            payload,
        )

    async def send_answer(
        self,
        peer_id: ID,
        sdp: str,
        sdp_type: str,
        certhash: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "type": "answer",
            "sdp": sdp,
            "sdpType": sdp_type,
            "certhash": certhash,
        }
        if extra:
            payload.update(extra)
        await self.send_signal(
            peer_id,
            payload,
        )

    async def send_ice_candidate(
        self,
        peer_id: ID,
        candidate: RTCIceCandidate | dict[str, Any] | None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Send ICE candidate with trickling support"""
        peer_id_str = str(peer_id)
        if isinstance(candidate, dict) or candidate is None:
            payload = candidate
        else:
            candidate_any = cast(Any, candidate)
            if hasattr(candidate_any, "to_sdp"):
                candidate_str = candidate_any.to_sdp()
            else:
                candidate_str = getattr(candidate_any, "candidate", None)
            payload = {
                "candidate": candidate_str,
                "sdpMid": candidate_any.sdpMid,
                "sdpMLineIndex": candidate_any.sdpMLineIndex,
            }
        candidate_msg: dict[str, Any] = {
            "type": "ice",
            "candidate": payload,
        }
        if extra:
            candidate_msg.update(extra)

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

    def enqueue_local_candidate(
        self,
        peer_id: ID | str,
        candidate_payload: dict[str, Any] | None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Record a locally gathered ICE candidate for later flushing."""
        peer_id_str = str(peer_id)
        self.pending_local_ice.setdefault(peer_id_str, []).append(
            (candidate_payload, extra)
        )

    async def flush_local_ice(self, peer_id: ID) -> None:
        """Send any queued local ICE candidates for the given peer."""
        peer_id_str = str(peer_id)
        pending = self.pending_local_ice.pop(peer_id_str, [])
        if not pending:
            return
        for payload, extra in pending:
            await self.send_ice_candidate(peer_id, payload, extra=extra)

    async def send_connection_state(
        self, peer_id: ID, state: str, reason: str | None = None
    ) -> None:
        """Send connection state update"""
        message = {"type": "connection_state", "state": state}
        if reason:
            message["reason"] = reason
        await self.send_signal(peer_id, message)

    async def negotiate_connection(
        self,
        peer_id: ID,
        offer: RTCSessionDescription,
        certhash: str,
        extra: dict[str, Any] | None = None,
    ) -> RTCSessionDescription:
        """Complete SDP offer/answer exchange with error handling and timeouts"""
        try:
            # Send offer
            await self.send_offer(peer_id, offer.sdp, offer.type, certhash, extra)

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

            prev_answer_handlers = list(self._handlers.get("answer", []))
            prev_error_handlers = list(self._handlers.get("error", []))

            # Set temporary handler for answer/error
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
        finally:
            # Restore previous handlers
            if prev_answer_handlers:
                self._handlers["answer"] = prev_answer_handlers
            else:
                self._handlers.pop("answer", None)
            if prev_error_handlers:
                self._handlers["error"] = prev_error_handlers
            else:
                self._handlers.pop("error", None)

    async def handle_incoming_connection(
        self, offer: RTCSessionDescription, sender_peer_id: str, certhash: str
    ) -> RTCSessionDescription:
        """Handle incoming connection offer and generate answer"""
        try:
            offer_msg = {
                "type": "offer",
                "sdp": offer.sdp,
                "sdpType": offer.type,
                "certhash": certhash,
            }
            handlers = self._handlers.get("offer", [])
            if not handlers:
                raise RuntimeError("No offer handler registered for signaling service")
            for handler in list(handlers):
                result = await handler(offer_msg, sender_peer_id)
                if isinstance(result, RTCSessionDescription):
                    return result
            raise RuntimeError(
                "Offer handlers did not return an RTCSessionDescription answer"
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
