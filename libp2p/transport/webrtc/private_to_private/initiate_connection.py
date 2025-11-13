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

from ..async_bridge import TrioSafeWebRTCOperations
from ..connection import WebRTCRawConnection
from ..constants import (
    DEFAULT_DIAL_TIMEOUT,
    SIGNALING_PROTOCOL,
    SDPHandshakeError,
    WebRTCError,
)
from .pb import Message
from .util import split_addr

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

    # Split multiaddr to get circuit address and target peer
    circuit_addr, target_peer_id = split_addr(maddr)
    logger.info(f"Circuit address: {circuit_addr}, Target peer: {target_peer_id}")

    # Variables for cleanup
    peer_connection = None
    signaling_stream = None

    try:
        # Establish connection to target peer through circuit relay
        # Following js-libp2p pattern: dial circuit address, then open signaling stream

        network = host.get_network()
        existing_connections = []
        if hasattr(network, "get_connections"):
            existing_connections = network.get_connections(target_peer_id)

        if not existing_connections:
            logger.debug(
                "No existing signaling connection to %s, attempting fallback dial",
                target_peer_id,
            )

            # Seed peerstore with circuit address if needed so dial_peer can succeed
            peerstore = host.get_peerstore()
            target_component = Multiaddr(f"/p2p/{target_peer_id.to_base58()}")
            try:
                base_addr = circuit_addr.decapsulate(target_component)
            except ValueError:
                base_addr = circuit_addr

            try:
                peerstore.add_addrs(target_peer_id, [base_addr], 3600)
            except Exception as exc:
                logger.debug(
                    "Failed to seed peerstore for %s with %s: %s",
                    target_peer_id,
                    base_addr,
                    exc,
                )

            try:
                await network.dial_peer(target_peer_id)
                existing_connections = network.get_connections(target_peer_id)
                logger.debug(
                    "Fallback dial established %d signaling connections to %s",
                    len(existing_connections),
                    target_peer_id,
                )
            except Exception as dial_exc:
                raise WebRTCError(
                    f"No signaling connection available to {target_peer_id}. "
                    "Call ensure_signaling_connection() before initiate_connection."
                ) from dial_exc

        if not existing_connections:
            raise WebRTCError(
                f"No signaling connection to {target_peer_id}. "
                "Call ensure_signaling_connection() before initiate_connection."
            )

        # Open signaling stream to target peer
        logger.debug(
            "Opening signaling stream to %s using protocol %s",
            target_peer_id,
            SIGNALING_PROTOCOL,
        )
        signaling_stream = await host.new_stream(target_peer_id, [SIGNALING_PROTOCOL])
        logger.info(
            "Established signaling stream through circuit relay to %s", target_peer_id
        )

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
            while peer_connection.iceGatheringState != "complete":
                await trio.sleep(0.05)

        logger.debug("Sending  SDP_offer to peer as initiator")
        # Send offer with all ICE candidates
        offer_msg = Message()
        offer_msg.type = Message.SDP_OFFER
        offer_msg.data = offer.sdp
        await _send_signaling_message(signaling_stream, offer_msg)
        logger.debug("Sent SDP offer to %s", target_peer_id)

        # (Note: aiortc does not emit ice candidate event, per candidate
        # but sends it along SDP.
        # To maintain interop, we extract and resend in given format)
        logger.debug("Sending ICE candidates to %s", target_peer_id)
        await _send_ice_candidates(signaling_stream, peer_connection)

        # Wait for answer
        logger.debug("Awaiting SDP answer from %s", target_peer_id)
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
        logger.debug("Handling incoming ICE candidates from %s", target_peer_id)
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
        # Use a single event to track completion and a flag for success/failure
        completion_event = trio.Event()
        success_result = False

        async def wait_for_success() -> None:
            nonlocal success_result
            try:
                await data_channel_ready.wait()
                success_result = True
                completion_event.set()
            except Exception as e:
                logger.debug(f"Error in wait_for_success: {e}")
                completion_event.set()

        async def wait_for_failure() -> None:
            try:
                await connection_failed.wait()
                completion_event.set()
            except Exception as e:
                logger.debug(f"Error in wait_for_failure: {e}")
                completion_event.set()

        try:
            with trio.move_on_after(timeout) as cancel_scope:
                try:
                    async with trio.open_nursery() as nursery:
                        nursery.start_soon(wait_for_success)
                        nursery.start_soon(wait_for_failure)
                        await completion_event.wait()
                        # Cancel nursery tasks since we got what we needed
                        # This is safe - tasks will handle cancellation gracefully
                        nursery.cancel_scope.cancel()
                except* trio.Cancelled:
                    # Cancellation is expected when we cancel the nursery
                    # Check if we got what we wanted before cancellation
                    if not data_channel_ready.is_set() and connection_failed.is_set():
                        raise WebRTCError("WebRTC connection failed")
                    # Otherwise, cancellation is fine if we got success
                except* Exception as eg:
                    # Handle ExceptionGroup from Trio nursery
                    # Extract meaningful exceptions (skip Cancelled)
                    errors = [
                        e for e in eg.exceptions if not isinstance(e, trio.Cancelled)
                    ]
                    if errors:
                        # Log all errors for debugging
                        for err in errors:
                            logger.error(f"Nursery task error: {err}", exc_info=err)
                        # Use the first error as the primary cause
                        primary_error = errors[0]
                        # Check if it's a connection failure
                        if connection_failed.is_set():
                            raise WebRTCError(
                                "WebRTC connection failed"
                            ) from primary_error
                        # Re-raise if it's already a WebRTCError
                        if isinstance(primary_error, WebRTCError):
                            raise primary_error
                        # Otherwise, wrap it
                        raise WebRTCError(
                            f"Connection establishment error: {primary_error}"
                        ) from primary_error
                    # If only cancellations, check our state
                    if connection_failed.is_set():
                        raise WebRTCError("WebRTC connection failed")
                    if not data_channel_ready.is_set():
                        raise WebRTCError("Unexpected exception group from nursery")

            # Check results after waiting
            if connection_failed.is_set():
                raise WebRTCError("WebRTC connection failed")

            if cancel_scope.cancelled_caught:
                if not data_channel_ready.is_set():
                    raise WebRTCError("Data channel connection timeout")

            if not data_channel_ready.is_set():
                raise WebRTCError("Data channel failed to open")

        except WebRTCError:
            # Re-raise WebRTCErrors as-is
            raise
        except Exception as e:
            # Handle any other exceptions
            # Check if it's a connection failure
            if connection_failed.is_set():
                raise WebRTCError("WebRTC connection failed") from e
            # Otherwise, wrap it
            raise WebRTCError(f"Connection establishment error: {e}") from e

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

        # Cleanup on failure - handle closed event loops gracefully
        # Note: This cleanup happens while still in the open_loop()
        #  context from transport.dial()
        if peer_connection:
            try:
                bridge = TrioSafeWebRTCOperations._get_bridge()
                try:
                    async with bridge:
                        await bridge.close_peer_connection(peer_connection)
                except (RuntimeError, Exception) as cleanup_error:
                    # Check if it's a closed loop issue
                    error_str = str(cleanup_error).lower()
                    if "closed" in error_str or "no running event loop" in error_str:
                        logger.debug("Event loop closed during cleanup (non-critical)")
                    else:
                        logger.warning(
                            f"Error cleaning up peer connection: {cleanup_error}"
                        )
            except Exception as cleanup_error:
                # Final fallback - log but don't fail
                error_str = str(cleanup_error).lower()
                if "closed" not in error_str:
                    logger.warning(
                        f"Unexpected err during conn cleanup: {cleanup_error}"
                    )

        if signaling_stream:
            try:
                await signaling_stream.close()
            except Exception as cleanup_error:
                logger.debug(
                    f"Error closing signaling stream during cleanup: {cleanup_error}"
                )

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
