import json
import logging
from typing import Any

from aioice.candidate import Candidate
from aiortc import (
    RTCConfiguration,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.rtcicetransport import candidate_from_aioice
from multiaddr import Multiaddr
import trio

from libp2p.abc import IHost, INetStream, IRawConnection
from libp2p.peer.id import ID

from ..async_bridge import TrioSafeWebRTCOperations
from ..connection import WebRTCRawConnection
from ..constants import (
    DEFAULT_DIAL_TIMEOUT,
    SIGNALING_PROTOCOL,
    SDPHandshakeError,
    WebRTCError,
)
from .pb import Message

logger = logging.getLogger("webrtc.private.initiate_connection")


async def initiate_connection(
    maddr: Multiaddr,
    rtc_config: RTCConfiguration,
    host: IHost,
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
    protocols = [p for p in maddr.protocols() if p is not None]
    target_peer_id = None
    for i, protocol in enumerate(protocols):
        if protocol.name == "p2p":
            if i + 1 < len(protocols) and protocols[i + 1].name == "p2p-circuit":
                continue
            else:
                # This is the target peer
                p2p_value = maddr.value_for_protocol("p2p")
                if p2p_value is not None:
                    target_peer_id = ID.from_base58(p2p_value)
                    break

    if not target_peer_id:
        raise WebRTCError(f"Cannot extract target peer ID from multiaddr: {maddr}")

    logger.info(f"Target peer ID: {target_peer_id}")

    # Variables for cleanup
    peer_connection = None
    signaling_stream = None

    try:
        # Establish signaling stream through circuit relay
        # Note: new_stream expects peer_id, not multiaddr
        # We need to extract the relay peer ID from the multiaddr
        relay_peer_id = None
        for i, protocol in enumerate(protocols):
            if protocol.name == "p2p":
                if i + 1 < len(protocols) and protocols[i + 1].name == "p2p-circuit":
                    # This is the relay peer
                    p2p_value = maddr.value_for_protocol("p2p")
                    if p2p_value is not None:
                        relay_peer_id = ID.from_base58(p2p_value)
                        break

        if not relay_peer_id:
            raise WebRTCError(f"Cannot extract relay peer ID from multiaddr: {maddr}")

        signaling_stream = await host.new_stream(relay_peer_id, [SIGNALING_PROTOCOL])
        logger.info("Established signaling stream through circuit relay")

        # Create RTCPeerConnection and data channel using safe operations
        (
            peer_connection,
            data_channel,
        ) = await TrioSafeWebRTCOperations.create_peer_conn_with_data_channel(
            rtc_config, "libp2p-webrtc"
        )

        logger.info("Created RTCPeerConnection and data channel")

        # Setup data channel ready event
        data_channel_ready = trio.Event()

        @data_channel.on("open")
        def on_data_channel_open() -> None:
            logger.info("Data channel opened")
            data_channel_ready.set()

        @data_channel.on("error")
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
            while peer_connection.iceGatheringState != "complete":
                await trio.sleep(0.05)

        logger.debug("Sending  SDP_offer to peer as initiator")
        # Send offer with all ICE candidates
        offer_msg = Message()
        offer_msg.type = Message.SDP_OFFER
        offer_msg.data = offer.sdp
        await _send_signaling_message(signaling_stream, offer_msg)

        # (Note: aiortc does not emit ice candidate event, per candidate (like js)
        # but sends it along SDP.
        # To maintain interop, we extract and resend in given format)
        await _send_ice_candidates(signaling_stream, peer_connection)

        # Wait for answer
        answer_msg = await _receive_signaling_message(signaling_stream, timeout)
        if answer_msg.type != Message.SDP_ANSWER:
            raise SDPHandshakeError(f"Expected answer, got: {answer_msg.type}")

        # Set remote description
        answer = RTCSessionDescription(sdp=answer_msg.data, type="answer")
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
            if peer_connection is not None:
                state = peer_connection.connectionState
                logger.debug(f"Connection state: {state}")
                if state == "failed":
                    connection_failed.set()

        # Register connection state handler
        if peer_connection is not None:
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

        logger.debug("initiator connected, closing init channel")
        data_channel.close()

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


async def _send_signaling_message(stream: INetStream, message: Message) -> None:
    """Send a signaling message over the stream"""
    try:
        # message_length = len(message_data).to_bytes(4, byteorder="big")
        await stream.write(message.SerializeToString())
        logger.debug(f"Sent signaling message: {message.type}")
    except Exception as e:
        logger.error(f"Failed to send signaling message: {e}")
        raise


async def _receive_signaling_message(stream: INetStream, timeout: float) -> Message:
    """Receive a signaling message from the stream"""
    try:
        with trio.move_on_after(timeout):
            # Read message data
            message_data = await stream.read()
            deserealized_msg = Message()
            deserealized_msg.ParseFromString(message_data)
            logger.debug(f"Received signaling message: {deserealized_msg.type}")
            return deserealized_msg

    except Exception as e:
        logger.error(f"Failed to receive signaling message: {e}")
        raise


async def _send_ice_candidates(
    stream: INetStream, peer_connection: RTCPeerConnection
) -> None:
    # Get SDP offer from localDescription to extract ICE Candidate
    sdp = peer_connection.localDescription.sdp
    sdp_lines = sdp.splitlines()

    msg = Message()
    msg.type = Message.ICE_CANDIDATE
    # Extract ICE_Candidate and send each separately
    for line in sdp_lines:
        if line.startswith("a=candidate:"):
            cand_str = line[len("a=") :]
            candidate_init = {"candidate": cand_str, "sdpMLineIndex": 0}
            data = json.dumps(candidate_init)
            msg.data = data
            await _send_signaling_message(stream, msg)
            logger.debug("Sent ICE candidate init: %s", candidate_init)
    # Mark end-of-candidates
    msg = Message(type=Message.ICE_CANDIDATE, data=json.dumps(None))
    await _send_signaling_message(stream, msg)
    logger.debug("Sent end-of-ICE marker")


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

            # stream ended or we became connected
            if not message:
                logger.error("Null message recieved")
                break

            if message.type != Message.ICE_CANDIDATE:
                logger.error("ICE candidate message expected. Exiting...")
                raise WebRTCError("ICE candidate message expected.")
                break

            # Candidate init cannot be null
            if message.data == "":
                logger.debug("candidate received is empty")
                continue

            logger.debug("Recieved new ICE Candidate")
            try:
                candidate_init = json.loads(message.data)
            except json.JSONDecodeError:
                logger.error("Invalid ICE candidate JSON: %s", message.data)
                break

            bridge = TrioSafeWebRTCOperations._get_bridge()

            # None means ICE gathering is fully complete
            if candidate_init is None:
                logger.debug("Received ICE candidate null → end-of-ice signal")
                async with bridge:
                    await bridge.add_ice_candidate(peer_connection, None)
                return

            # CandidateInit is expected to be a dict
            if isinstance(candidate_init, dict) and "candidate" in candidate_init:
                candidate = candidate_from_aioice(
                    Candidate.from_sdp(candidate_init["candidate"])
                )
                async with bridge:
                    await bridge.add_ice_candidate(peer_connection, candidate)
                logger.debug("Added ICE candidate: %r", candidate_init)

        except Exception as e:
            logger.warning(f"Error handling ICE candidate: {e}")
            break


async def _wait_for_event(event: trio.Event) -> None:
    """Wait for a trio event to be set"""
    await event.wait()
