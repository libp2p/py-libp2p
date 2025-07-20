import json
import logging
from typing import Any

from aiortc import (
    RTCConfiguration,
    RTCIceCandidate,
    RTCPeerConnection,
    RTCSessionDescription,
)
from multiaddr import Multiaddr
import trio

from libp2p.abc import INetStream, IRawConnection
from libp2p.peer.id import ID

from ..async_bridge import TrioSafeWebRTCOperations
from ..connection import WebRTCRawConnection
from ..constants import (
    DEFAULT_DIAL_TIMEOUT,
    SIGNALING_PROTOCOL,
    SDPHandshakeError,
    WebRTCError,
)

logger = logging.getLogger("webrtc.private.initiate_connection")


async def initiate_connection(
    maddr: Multiaddr,
    rtc_config: RTCConfiguration,
    host: Any,
    timeout: float = DEFAULT_DIAL_TIMEOUT,
) -> IRawConnection:
    """
    Initiate WebRTC connection through circuit relay signaling.

    This function acts as the "offerer" in the WebRTC handshake:
    1. Establishes signaling stream through circuit relay
    2. Creates SDP offer with ICE candidates
    3. Exchanges offer/answer with remote peer
    4. Waits for data channel to be established
    """
    logger.info(f"Initiating WebRTC connection to {maddr}")

    # Parse circuit relay multiaddr to get target peer ID
    protocols = maddr.protocols()
    target_peer_id = None
    for i, protocol in enumerate(protocols):
        if protocol.name == "p2p":
            if i + 1 < len(protocols) and protocols[i + 1].name == "p2p-circuit":
                # This is the relay peer, continue
                continue
            else:
                # This is the target peer
                target_peer_id = ID.from_base58(maddr.value_for_protocol("p2p"))
                break

    if not target_peer_id:
        raise WebRTCError(f"Cannot extract target peer ID from multiaddr: {maddr}")

    logger.info(f"Target peer ID: {target_peer_id}")

    # Variables for cleanup
    peer_connection = None
    signaling_stream = None

    try:
        # Establish signaling stream through circuit relay
        signaling_stream = await host.new_stream(maddr, [SIGNALING_PROTOCOL])
        logger.info("Established signaling stream through circuit relay")

        # Create RTCPeerConnection and data channel using safe operations
        (
            peer_connection,
            data_channel,
        ) = await TrioSafeWebRTCOperations.create_peer_conn_with_data_channel(
            rtc_config, "libp2p-webrtc"
        )

        logger.info("Created RTCPeerConnection and data channel")

        # Setup ICE candidate collection
        ice_candidates: list[Any] = []
        ice_gathering_complete = trio.Event()

        def on_ice_candidate(candidate: Any) -> None:
            if candidate:
                ice_candidates.append(candidate)
                logger.debug(f"Generated ICE candidate: {candidate.candidate}")
            else:
                # End of candidates signaled
                ice_gathering_complete.set()
                logger.debug("ICE gathering complete")

        # Register ICE candidate handler
        peer_connection.on("icecandidate", on_ice_candidate)

        # Setup data channel ready event
        data_channel_ready = trio.Event()

        def on_data_channel_open() -> None:
            logger.info("Data channel opened")
            data_channel_ready.set()

        def on_data_channel_error(error: Any) -> None:
            logger.error(f"Data channel error: {error}")

        # Register data channel event handlers
        data_channel.on("open", on_data_channel_open)
        data_channel.on("error", on_data_channel_error)

        # Create and send SDP offer with async bridge
        bridge = TrioSafeWebRTCOperations._get_bridge()
        async with bridge:
            offer = await bridge.create_offer(peer_connection)
            await bridge.set_local_description(peer_connection, offer)

        # Wait for ICE gathering to complete
        with trio.move_on_after(timeout):
            await ice_gathering_complete.wait()

        # Send offer with all ICE candidates
        offer_msg = {"type": "offer", "sdp": offer.sdp, "sdpType": "offer"}
        await _send_signaling_message(signaling_stream, offer_msg)

        # Send ICE candidates
        for candidate in ice_candidates:
            candidate_msg = {
                "type": "ice-candidate",
                "candidate": candidate.candidate,
                "sdpMid": candidate.sdpMid,
                "sdpMLineIndex": candidate.sdpMLineIndex,
            }
            await _send_signaling_message(signaling_stream, candidate_msg)

        # Signal end of candidates
        end_msg = {"type": "ice-candidate-end"}
        await _send_signaling_message(signaling_stream, end_msg)

        logger.info("Sent offer and ICE candidates")

        # Wait for answer
        answer_msg = await _receive_signaling_message(signaling_stream, timeout)
        if answer_msg.get("type") != "answer":
            raise SDPHandshakeError(f"Expected answer, got: {answer_msg.get('type')}")

        # Set remote description
        answer = RTCSessionDescription(
            sdp=answer_msg["sdp"], type=answer_msg["sdpType"]
        )
        bridge = TrioSafeWebRTCOperations._get_bridge()
        async with bridge:
            await bridge.set_remote_description(peer_connection, answer)

        logger.info("Set remote description from answer")

        # Handle incoming ICE candidates
        await _handle_incoming_ice_candidates(
            signaling_stream, peer_connection, timeout
        )

        # Wait for data channel to be ready
        connection_failed = trio.Event()

        def on_connection_state_change() -> None:
            state = peer_connection.connectionState
            logger.debug(f"Connection state: {state}")
            if state == "failed":
                connection_failed.set()

        # Register connection state handler
        peer_connection.on("connectionstatechange", on_connection_state_change)

        # Wait for either success or failure
        with trio.move_on_after(timeout) as cancel_scope:
            async with trio.open_nursery() as nursery:
                nursery.start_soon(_wait_for_event, data_channel_ready)
                nursery.start_soon(_wait_for_event, connection_failed)

                # Break out when either event is set
                if data_channel_ready.is_set():
                    nursery.cancel_scope.cancel()
                elif connection_failed.is_set():
                    raise WebRTCError("WebRTC connection failed")

        if cancel_scope.cancelled_caught:
            raise WebRTCError("Data channel connection timeout")

        if not data_channel_ready.is_set():
            raise WebRTCError("Data channel failed to open")

        # Create connection wrapper
        connection = WebRTCRawConnection(
            peer_id=target_peer_id,
            peer_connection=peer_connection,
            data_channel=data_channel,
            is_initiator=True,
        )

        logger.info(f"Successfully established WebRTC connection to {target_peer_id}")
        return connection

    except Exception as e:
        logger.error(f"Failed to initiate WebRTC connection: {e}")

        # Cleanup on failure
        if peer_connection:
            try:
                await TrioSafeWebRTCOperations.cleanup_webrtc_resources(peer_connection)
            except Exception as cleanup_error:
                logger.warning(f"Error cleaning up peer connection: {cleanup_error}")

        if signaling_stream:
            try:
                await signaling_stream.close()
            except Exception as cleanup_error:
                logger.warning(f"Error cleaning up signaling stream: {cleanup_error}")

        raise WebRTCError(f"Connection initiation failed: {e}") from e


async def _send_signaling_message(stream: INetStream, message: dict[str, Any]) -> None:
    """Send a signaling message over the stream"""
    try:
        message_data = json.dumps(message).encode("utf-8")
        message_length = len(message_data).to_bytes(4, byteorder="big")
        await stream.write(message_length + message_data)
        logger.debug(f"Sent signaling message: {message['type']}")
    except Exception as e:
        logger.error(f"Failed to send signaling message: {e}")
        raise


async def _receive_signaling_message(
    stream: INetStream, timeout: float
) -> dict[str, Any]:
    """Receive a signaling message from the stream"""
    try:
        with trio.move_on_after(timeout) as cancel_scope:
            # Read message length
            length_data = await stream.read(4)
            if len(length_data) != 4:
                raise WebRTCError("Failed to read message length")

            message_length = int.from_bytes(length_data, byteorder="big")

            # Read message data
            message_data = await stream.read(message_length)
            if len(message_data) != message_length:
                raise WebRTCError("Failed to read complete message")

            message = json.loads(message_data.decode("utf-8"))
            logger.debug(f"Received signaling message: {message.get('type')}")
            return message

        if cancel_scope.cancelled_caught:
            raise WebRTCError("Signaling message receive timeout")

    except Exception as e:
        logger.error(f"Failed to receive signaling message: {e}")
        raise


async def _handle_incoming_ice_candidates(
    stream: INetStream, peer_connection: RTCPeerConnection, timeout: float
) -> None:
    """Handle incoming ICE candidates from the signaling stream"""
    logger.debug("Handling incoming ICE candidates")

    while True:
        try:
            with trio.move_on_after(timeout) as cancel_scope:
                message = await _receive_signaling_message(stream, timeout)

            if cancel_scope.cancelled_caught:
                logger.warning("ICE candidate receive timeout")
                break

            if message.get("type") == "ice-candidate":
                # Add ICE candidate
                candidate = RTCIceCandidate(
                    component=message.get("component", 1),
                    foundation=message.get("foundation", ""),
                    ip=message.get("ip", ""),
                    port=message.get("port", 0),
                    priority=message.get("priority", 0),
                    protocol=message.get("protocol", "udp"),
                    type=message.get("candidateType", "host"),
                    sdpMid=message.get("sdpMid"),
                    sdpMLineIndex=message.get("sdpMLineIndex"),
                )

                bridge = TrioSafeWebRTCOperations._get_bridge()
                async with bridge:
                    await bridge.add_ice_candidate(peer_connection, candidate)

                logger.debug(f"Added ICE candidate: {candidate.type}")

            elif message.get("type") == "ice-candidate-end":
                logger.debug("Received end of ICE candidates")
                break
            else:
                logger.warning(
                    f"Unexpected message during ICE exchange: {message.get('type')}"
                )

        except Exception as e:
            logger.warning(f"Error handling ICE candidate: {e}")
            break


async def _wait_for_event(event: trio.Event) -> None:
    """Wait for a trio event to be set"""
    await event.wait()
