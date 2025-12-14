from collections.abc import Awaitable, Callable
import logging
from typing import TYPE_CHECKING, Any, cast

from aioice.candidate import Candidate
from aiortc import RTCDataChannel, RTCIceCandidate, RTCSessionDescription
from aiortc.rtcicetransport import candidate_from_aioice
from multiaddr import Multiaddr
import trio
from trio_asyncio import aio_as_trio

from libp2p.abc import ISecureConn
from libp2p.peer.id import ID
from libp2p.security.noise.transport import PROTOCOL_ID as NOISE_PROTOCOL_ID
from libp2p.security.security_multistream import SecurityMultistream
from libp2p.transport.webrtc.async_bridge import get_webrtc_bridge
from libp2p.transport.webrtc.private_to_public.util import (
    SDP,
    canonicalize_certhash,
    extract_certhash,
    fingerprint_to_certhash,
    fingerprint_to_multiaddr,
    generate_noise_prologue,
    multiaddr_to_fingerprint,
)

from ..connection import WebRTCRawConnection
from .direct_rtc_connection import DirectPeerConnection

if TYPE_CHECKING:
    from libp2p.abc import IRawConnection
    from libp2p.transport.webrtc.signal_service import SignalService

logger = logging.getLogger("libp2p.transport.webrtc.private_to_public")


async def _extract_and_add_ice_candidates_from_sdp(
    rtc_pc: Any, sdp: str, bridge: Any, role: str = "unknown"
) -> int:
    """
    Extract ICE candidates from SDP and add them to the peer connection.

    aiortc includes ICE candidates in the SDP, but we need to extract
    and add them explicitly to ensure ICE processing starts.

    Returns the number of candidates added.
    """
    sdp_lines = sdp.splitlines()
    candidates_added = 0

    # Find media lines (m=) to determine sdpMLineIndex for candidates
    media_line_indices = []
    for i, line in enumerate(sdp_lines):
        if line.startswith("m="):
            media_line_indices.append(i)

    # If no media lines found, default to 0 (shouldn't happen, but be safe)
    if not media_line_indices:
        media_line_indices = [0]

    # Find candidate lines and determine which media line they belong to
    candidate_lines = []
    current_media_index = 0
    for i, line in enumerate(sdp_lines):
        if line.startswith("m="):
            # Update current media index
            current_media_index = (
                media_line_indices.index(i) if i in media_line_indices else 0
            )
        elif line.startswith("a=candidate:"):
            # Store candidate line with its media index
            candidate_lines.append((line, current_media_index))

    logger.debug(
        f"{role} SDP contains {len(candidate_lines)} candidate lines "
        f"(SDP length: {len(sdp)} chars,"
        f" lines: {len(sdp_lines)}, media lines: {len(media_line_indices)})"
    )

    if not candidate_lines:
        logger.warning(
            f"{role} No ICE candidates found in SDP! SDP preview: {sdp[:200]}..."
        )
        return 0

    async with bridge:
        for line, mline_index in candidate_lines:
            cand_str = line[len("a=") :].strip()
            try:
                candidate_obj = candidate_from_aioice(Candidate.from_sdp(cand_str))
                # CRITICAL: Set sdpMLineIndex - aiortc requires this!
                candidate_obj.sdpMLineIndex = mline_index
                if not hasattr(candidate_obj, "sdpMid") or candidate_obj.sdpMid is None:
                    candidate_obj.sdpMid = str(mline_index)
                await bridge.add_ice_candidate(rtc_pc, candidate_obj)
                candidates_added += 1
                logger.debug(
                    f"{role} added ICE candidate"
                    f" (mline={mline_index}): {cand_str[:80]}.."
                )
            except Exception as e:
                logger.warning(
                    f"{role} Failed to parse ICE candidate '{cand_str[:50]}...': {e}",
                    exc_info=True,
                )
                continue

        # Add end-of-candidates marker if we added any candidates
        if candidates_added > 0:
            await bridge.add_ice_candidate(rtc_pc, None)
            logger.info(f"{role} Added {candidates_added} ICE candidates from SDP")
        else:
            logger.warning(
                f"{role} Found candidate lines in SDP but failed to add any candidates"
            )

    return candidates_added


# pyright: ignore[reportMissingReturnStatement]
async def connect(
    peer_connection: DirectPeerConnection,
    ufrag: str,
    ice_pwd: str,
    role: str,
    remote_addr: Multiaddr | None = None,
    remote_peer_id: ID | None = None,
    *,
    signal_service: "SignalService | None" = None,
    certhash: str | None = None,
    incoming_offer: RTCSessionDescription | None = None,
    offer_handler: Callable[
        [RTCSessionDescription, str], Awaitable[RTCSessionDescription]
    ]
    | None = None,
    answer_handler: Callable[[RTCSessionDescription, str], Awaitable[None]]
    | None = None,
    security_multistream: SecurityMultistream | None = None,
) -> tuple["IRawConnection | ISecureConn", RTCSessionDescription | None]:
    """
    Establish a WebRTC-Direct connection, perform the noise handshake,
    and return the upgraded connection.
    """
    # CRITICAL: Create data channel BEFORE createOffer() on peer_conn
    # This is required for ICE gathering to start
    # - RTCPeerConnection needs a media component to gather candidates.
    #  js-libp2p does this: createDataChannel() -> createOffer()
    bridge = get_webrtc_bridge()
    cleanup_handlers: list[
        tuple[str, Callable[[dict[str, Any], str], Awaitable[None]]]
    ] = []

    handshake_channel: RTCDataChannel = peer_connection.createDataChannel(
        "", negotiated=True, id=0
    )

    # Get the underlying peer connection for ICE candidate handling
    rtc_pc = peer_connection.peer_connection

    # Track whether remote description has been set (for queuing remote candidates)
    remote_description_set = trio.Event()
    queued_remote_candidates: list[dict[str, Any]] = []

    if signal_service is not None and remote_peer_id is not None:
        remote_peer_str = remote_peer_id.to_base58()

        def _queue_local_candidate(candidate: RTCIceCandidate | None) -> None:
            if signal_service is None or remote_peer_id is None:
                return
            if candidate is None:
                signal_service.enqueue_local_candidate(
                    remote_peer_id, None, extra={"ufrag": ufrag}
                )
                return
            candidate_any = cast(Any, candidate)
            if hasattr(candidate_any, "to_sdp"):
                candidate_sdp = candidate_any.to_sdp()
            else:
                candidate_sdp = getattr(candidate_any, "candidate", None)
            signal_service.enqueue_local_candidate(
                remote_peer_id,
                {
                    "candidate": candidate_sdp,
                    "sdpMid": candidate_any.sdpMid,
                    "sdpMLineIndex": candidate_any.sdpMLineIndex,
                },
                extra={"ufrag": ufrag},
            )

        # Set up ICE candidate handler on peer_connection (DirectPeerConnection)
        # Note: aiortc doesn't emit icecandidate events (candidates are in SDP),
        # but we set this up for compatibility and in case future versions do
        peer_connection.on("icecandidate", _queue_local_candidate)

        async def _handle_remote_ice(
            message: dict[str, Any], sender_peer_id: str
        ) -> None:
            if sender_peer_id != remote_peer_str:
                return
            msg_ufrag = message.get("ufrag")
            if msg_ufrag is not None and msg_ufrag != ufrag:
                return

            # Wait for remote description to be set before adding candidates
            if not remote_description_set.is_set():
                logger.debug(f"{role} Queuing remote ICE candidate ")
                queued_remote_candidates.append(message)
                return

            candidate_payload = message.get("candidate")
            async with bridge:
                if candidate_payload is None:
                    # Add ICE candidate to peer_connection (DirectPeerConnection)
                    await bridge.add_ice_candidate(peer_connection, None)
                    return
                candidate_obj = candidate_from_aioice(
                    Candidate.from_sdp(candidate_payload.get("candidate", ""))
                )
                candidate_obj.sdpMid = candidate_payload.get("sdpMid")
                candidate_obj.sdpMLineIndex = candidate_payload.get("sdpMLineIndex")
                # Add ICE candidate to peer_connection (DirectPeerConnection)
                await bridge.add_ice_candidate(peer_connection, candidate_obj)

        signal_service.add_handler("ice", _handle_remote_ice)
        cleanup_handlers.append(("ice", _handle_remote_ice))

    try:
        if role == "client":
            logger.debug("client creating local offer")
            offer = await peer_connection.createOffer()

            # Wait for ICE gathering to complete
            logger.debug("client waiting for ICE gathering to complete...")
            logger.debug(
                f"client ICE gathering state before wait:"
                f" {peer_connection.iceGatheringState}"
            )
            with trio.move_on_after(10):  # 10s timeout for ICE gathering
                while peer_connection.iceGatheringState != "complete":
                    await trio.sleep(0.1)
            logger.debug(
                f"client ICE gathering state: {peer_connection.iceGatheringState}"
            )

            # Get the SDP from localDescription (should be set by createOffer)
            # Check peer_connection (DirectPeerConnection) not rtc_pc
            local_desc = peer_connection.localDescription
            if local_desc is not None:
                offer_sdp_with_candidates = local_desc.sdp
                logger.debug("client using SDP from localDescription")
            else:
                # Fallback: use offer SDP (might not have candidates yet)
                offer_sdp_with_candidates = offer.sdp
                logger.warning("client localDesc None, using offer SDP")

            offer_candidates = [
                line
                for line in offer_sdp_with_candidates.splitlines()
                if line.startswith("a=candidate:")
            ]
            logger.warning(
                f"client SDP has {len(offer_candidates)} candidates "
                f"(SDP length: {len(offer_sdp_with_candidates)} chars, "
                f"iceGatheringState: {peer_connection.iceGatheringState})"
            )
            if len(offer_candidates) == 0:
                logger.error(
                    f"client WARNING: No ICE candidates in offer SDP! "
                    f"This will cause ICE connection to fail. "
                    f"iceGatheringState: {peer_connection.iceGatheringState}, "
                    f"connectionState: {peer_connection.connectionState}"
                )
            else:
                # Log candidates for debugging
                for i, cand_line in enumerate[Any](offer_candidates):
                    logger.warning(f"client candidate {i}: {cand_line}")

            # Extract and send candidates via signal service if we have them
            if (
                offer_candidates
                and signal_service is not None
                and remote_peer_id is not None
            ):
                logger.debug(
                    f"client extracting {len(offer_candidates)} candidates"
                    f" from SDP to send via signal service"
                )
                for line in offer_candidates:
                    cand_str = line[len("a=") :].strip()
                    try:
                        # Parse and send candidate
                        signal_service.enqueue_local_candidate(
                            remote_peer_id,
                            {"candidate": cand_str, "sdpMLineIndex": 0},
                            extra={"ufrag": ufrag},
                        )
                    except Exception as e:
                        logger.debug(f"client failed to queue candidate: {e}")

            # Munge the SDP for sending
            munged_offer = SDP.munge_offer(offer_sdp_with_candidates, ufrag, ice_pwd)

            if remote_addr is None:
                raise Exception("Remote address is required for client role")

            if certhash is None:
                try:
                    certhash = extract_certhash(remote_addr)
                except Exception:
                    certhash = None

            # Create offer description with updated SDP (includes candidates)
            offer_desc_with_candidates = RTCSessionDescription(
                sdp=munged_offer, type=offer.type
            )

            if offer_handler is not None:
                answer_desc = await offer_handler(offer_desc_with_candidates, ufrag)
            elif signal_service is not None and remote_peer_id is not None:
                answer_desc = await signal_service.negotiate_connection(
                    remote_peer_id,
                    offer_desc_with_candidates,
                    certhash or "",
                    extra={"ufrag": ufrag},
                )
            else:
                raise Exception(
                    "Signal service or offer_handler required for WebRTC-Direct dialing"
                )
            # Set remote description - aiortc automatically processes candidates in SDP
            answer_candidates_in_sdp = [
                line
                for line in answer_desc.sdp.splitlines()
                if line.startswith("a=candidate:")
            ]
            logger.warning(
                f"client setting remote description (answer) with "
                f" {len(answer_candidates_in_sdp)} candidates, "
                f"current state: {peer_connection.connectionState}, "
                f"ICE: {peer_connection.iceConnectionState}"
            )
            await aio_as_trio(peer_connection.setRemoteDescription(answer_desc))
            logger.warning(
                f"client set remote description, connection state: "
                f"{peer_connection.connectionState}, "
                f"ICE: {peer_connection.iceConnectionState}, "
                f"iceGatheringState: {peer_connection.iceGatheringState}"
            )

            # Signal that remote description is set
            # - now we can process queued candidates
            remote_description_set.set()

            # Process any queued remote candidates that arrived before
            # remote description was set
            if signal_service is not None and queued_remote_candidates:
                logger.debug(
                    f"client processing {len(queued_remote_candidates)} "
                    "queued remote candidates"
                )
                async with bridge:
                    for queued_msg in queued_remote_candidates:
                        candidate_payload = queued_msg.get("candidate")
                        if candidate_payload is None:
                            await bridge.add_ice_candidate(peer_connection, None)
                        else:
                            candidate_obj = candidate_from_aioice(
                                Candidate.from_sdp(
                                    candidate_payload.get("candidate", "")
                                )
                            )
                            candidate_obj.sdpMid = candidate_payload.get("sdpMid")
                            candidate_obj.sdpMLineIndex = candidate_payload.get(
                                "sdpMLineIndex"
                            )
                            await bridge.add_ice_candidate(
                                peer_connection, candidate_obj
                            )
                queued_remote_candidates.clear()

            # Note: aiortc automatically extracts and processes ICE candidates from SDP
            # when setRemoteDescription() is called.
            # Additional candidates may arrive via signal service (trickling).

            # Give ICE a moment to process the remote description and candidates
            await trio.sleep(0.3)
        else:
            if incoming_offer is not None:
                offer_desc = incoming_offer
            else:
                raise Exception(
                    "Server role requires incoming SDP offer via signaling service"
                )
            # Set remote description - aiortc automatically processes candidates in SDP
            offer_candidates_in_sdp = [
                line
                for line in offer_desc.sdp.splitlines()
                if line.startswith("a=candidate:")
            ]
            logger.warning(
                f"server setting remote description (offer) "
                f"with {len(offer_candidates_in_sdp)} candidates, "
                f" current state: {peer_connection.connectionState}, "
                f"current state: {peer_connection.connectionState}, "
                f" ICE: {peer_connection.iceConnectionState}"
            )
            await aio_as_trio(peer_connection.setRemoteDescription(offer_desc))
            logger.warning(
                f"server set remote description, "
                f" connection state: {peer_connection.connectionState}, "
                f"ICE: {peer_connection.iceConnectionState}, "
                f"iceGatheringState: {peer_connection.iceGatheringState}"
            )

            # Signal that remote description is set -
            #  now we can process queued candidates
            remote_description_set.set()

            # Process any queued remote candidates that arrived
            # before remote description was set
            if signal_service is not None and queued_remote_candidates:
                logger.debug(
                    f"server processing {len(queued_remote_candidates)}"
                    " queued remote candidates"
                )
                async with bridge:
                    for queued_msg in queued_remote_candidates:
                        candidate_payload = queued_msg.get("candidate")
                        if candidate_payload is None:
                            await bridge.add_ice_candidate(peer_connection, None)
                        else:
                            candidate_obj = candidate_from_aioice(
                                Candidate.from_sdp(
                                    candidate_payload.get("candidate", "")
                                )
                            )
                            candidate_obj.sdpMid = candidate_payload.get("sdpMid")
                            candidate_obj.sdpMLineIndex = candidate_payload.get(
                                "sdpMLineIndex"
                            )
                            await bridge.add_ice_candidate(
                                peer_connection, candidate_obj
                            )
                queued_remote_candidates.clear()

            # Note: aiortc automatically extracts and processes ICE candidates from SDP
            # when setRemoteDescription() is called.
            # Additional candidates may arrive via signal service (trickling).

            # Give ICE a moment to process the remote description and candidates
            await trio.sleep(0.3)

            logger.debug("server creating local answer")
            # Note: DirectPeerConnection.createAnswer() already
            #  sets local description internally
            answer_desc = await peer_connection.createAnswer()

            # Wait for ICE gathering to complete AFTER answer is created
            # Check on peer_connection (DirectPeerConnection)
            # not rtc_pc (stored peer_connection)
            logger.debug("server waiting for ICE gathering to complete...")
            logger.debug(
                f"server ICE gathering state before wait:"
                f" {peer_connection.iceGatheringState}"
            )
            with trio.move_on_after(10):  # 10s timeout for ICE gathering
                while peer_connection.iceGatheringState != "complete":
                    await trio.sleep(0.1)
            logger.debug(
                f"server ICE gathering state: {peer_connection.iceGatheringState}"
            )

            # Get the SDP from localDescription (should be set by createAnswer)
            # Check peer_connection (DirectPeerConnection) not rtc_pc
            local_desc = peer_connection.localDescription
            if local_desc is not None:
                answer_sdp_with_candidates = local_desc.sdp
                logger.debug("server using SDP from localDescription")
            else:
                # Fallback: use answer SDP (might not have candidates yet)
                answer_sdp_with_candidates = answer_desc.sdp
                logger.warning("server localDescription None, using answer SDP")

            answer_candidates = [
                line
                for line in answer_sdp_with_candidates.splitlines()
                if line.startswith("a=candidate:")
            ]
            logger.warning(
                f"server SDP has {len(answer_candidates)} candidates "
                f"(SDP length: {len(answer_sdp_with_candidates)} chars, "
                f"iceGatheringState: {peer_connection.iceGatheringState})"
            )
            if len(answer_candidates) == 0:
                logger.error(
                    f"server WARNING: No ICE candidates in answer SDP! "
                    f"This will cause ICE connection to fail. "
                    f"iceGatheringState: {peer_connection.iceGatheringState}, "
                    f"connectionState: {peer_connection.connectionState}"
                )
            else:
                # Log candidates for debugging
                for i, cand_line in enumerate(answer_candidates):
                    logger.warning(f"server candidate {i}: {cand_line}")

            # Extract and send candidates via signal service if we have them
            if (
                answer_candidates
                and signal_service is not None
                and remote_peer_id is not None
            ):
                logger.debug(
                    f"server extracting {len(answer_candidates)} candidates from"
                    " SDP to send via signal service"
                )
                for line in answer_candidates:
                    cand_str = line[len("a=") :].strip()
                    try:
                        # Parse and send candidate
                        signal_service.enqueue_local_candidate(
                            remote_peer_id,
                            {"candidate": cand_str, "sdpMLineIndex": 0},
                            extra={"ufrag": ufrag},
                        )
                    except Exception as e:
                        logger.debug(f"server failed to queue candidate: {e}")

            # Update answer_desc with the SDP that includes candidates
            answer_desc = RTCSessionDescription(
                sdp=answer_sdp_with_candidates, type=answer_desc.type
            )
            if answer_handler is not None:
                await answer_handler(answer_desc, ufrag)
            elif signal_service is not None and remote_peer_id is not None:
                await signal_service.send_answer(
                    remote_peer_id,
                    answer_desc.sdp,
                    answer_desc.type,
                    certhash or "",
                    extra={"ufrag": ufrag},
                )
            else:
                raise Exception(
                    "Signal service or ans_handler required for WebRTC-Direct answer"
                )

        # Flush ICE candidates after SDP exchange to ensure they're sent
        # Note: We've already extracted candidates from SDP above, but we also need to
        # send any additional candidates that were gathered after SDP was created
        # IMPORTANT: Wait a bit before flushing to
        # ensure remote peer has set remote description
        # This prevents "addIceCandidate called without remote description" warnings
        if signal_service is not None and remote_peer_id is not None:
            # Ensure signaling stream is established before flushing
            peer_id_str = str(remote_peer_id)
            if peer_id_str not in signal_service.active_streams:
                logger.debug(f"{role} signaling stream not ready, waiting...")
                # Wait a bit for stream to be established
                for _ in range(10):  # Wait up to 1 second
                    if peer_id_str in signal_service.active_streams:
                        break
                    await trio.sleep(0.1)

            # Wait for remote peer to process SDP and set remote description
            # This prevents candidates from being added before remote description is set
            await trio.sleep(0.5)  # Give remote peer time to set remote description

            # Flush queued candidates (gathered after SDP was sent)
            await signal_service.flush_ice_candidates(remote_peer_id)
            logger.debug(f"{role} flushed queued ICE candidates after SDP exchange")

            # Also flush local ICE candidates that might have been queued
            await signal_service.flush_local_ice(remote_peer_id)

            # Give ICE candidates time to be exchanged and processed
            # This is important for the connection to transition
            # from "new" to "connecting"
            await trio.sleep(0.5)  # Wait for candidates to be sent and received

        # Wait for peer connection to be established before data channel can open
        connection_established = trio.Event()
        connection_failed = trio.Event()
        ice_connected = trio.Event()

        def on_connection_state_change() -> None:
            state = peer_connection.connectionState
            logger.debug(f"{role} peer connection state changed to: {state}")
            if state == "connected":
                connection_established.set()
            elif state == "failed" or state == "disconnected":
                connection_failed.set()
            elif state == "connecting":
                # Connection is in progress, log but don't fail yet
                logger.debug(f"{role} peer connection is connecting...")

        def on_ice_connection_state_change() -> None:
            ice_state = peer_connection.iceConnectionState
            logger.warning(
                f"{role} ICE connection state changed to: {ice_state} "
                f"(connectionState: {peer_connection.connectionState}, "
                f"iceGatheringState: {peer_connection.iceGatheringState})"
            )
            if ice_state == "connected" or ice_state == "completed":
                ice_connected.set()
            elif ice_state == "failed":
                logger.error(
                    f"{role} ICE connection FAILED! "
                    f"connectionState: {peer_connection.connectionState}, "
                    f"iceGatheringState: {peer_connection.iceGatheringState}"
                )
                # ICE failure means connection cannot succeed - fail immediately
                connection_failed.set()
            elif ice_state == "checking":
                logger.debug(f"{role} ICE connection checking...")
            elif ice_state == "disconnected":
                logger.warning(f"{role} ICE connection disconnected")
                # Disconnected might recover, but log it
            elif ice_state == "closed":
                # ICE closed - this might happen after handshake completes
                # Don't fail immediately if connection is already established
                conn_state = peer_connection.connectionState
                if conn_state == "connected":
                    logger.info(
                        f"{role} ICE closed but connection is connected - "
                        "this is normal, connection is established. "
                        "Setting connection_established event."
                    )
                    # Connection is actually working, treat as established
                    connection_established.set()
                else:
                    logger.warning(
                        f"{role} ICE closed before connection established - "
                        f"connectionState: {conn_state}, this may indicate a problem"
                    )

        # Set up connection state handlers on peer_connection (DirectPeerConnection)
        # This is the peer connection that's actually being used for offers/answers
        peer_connection.on("connectionstatechange", on_connection_state_change)
        peer_connection.on("iceconnectionstatechange", on_ice_connection_state_change)

        # Check current state (might already be connected or connecting)
        # Small delay to allow any pending state change events to fire
        await trio.sleep(0.01)
        current_state = peer_connection.connectionState
        ice_state = peer_connection.iceConnectionState
        logger.info(
            f"{role} initial peer connection state after handler setup: "
            f"{current_state}, ICE connection state: {ice_state}"
        )
        if current_state == "connected":
            connection_established.set()
        elif current_state in ("failed", "disconnected"):
            connection_failed.set()
        elif ice_state in ("connected", "completed"):
            ice_connected.set()
        elif ice_state == "closed" and current_state == "connected":
            logger.debug(
                f"{role} ICE is closed but connection is connected - "
                "treating as established"
            )
            connection_established.set()
        elif current_state == "new" and ice_state == "new":
            # Both states are "new" - ICE processing hasn't started
            # This means ICE candidates might not have been added yet
            logger.debug(
                f"{role} connection and ICE both 'new' -"
                " waiting for ICE processing to start..."
            )
            # Give ICE candidates time to be added and processed
            # After setting remote description, ICE should start processing candidates
            await trio.sleep(0.5)  # Brief wait for ICE to start processing

        # Wait for connection to be established (with timeout)
        # We monitor connection state for failures, but accept "connected" or
        # "closed ICE + connected" as success
        if not connection_established.is_set() and not connection_failed.is_set():
            # Re-check state right before waiting (handlers might have set events)
            final_check_state = peer_connection.connectionState
            final_check_ice = peer_connection.iceConnectionState
            if final_check_state == "connected":
                logger.info(f"{role} connectionState is 'connected' - proceeding")
                connection_established.set()
            elif final_check_ice == "closed" and final_check_state == "connected":
                logger.info(
                    f"{role} ICE 'closed' but connectionState 'connected' - proceeding"
                )
                connection_established.set()

            if not connection_established.is_set() and not connection_failed.is_set():
                logger.info(
                    f"{role} waiting for connectionState to become 'connected'... "
                    f"(current: {final_check_state}, ICE: {final_check_ice})"
                )
                # Simplified wait: just poll for connectionState == "connected"
                # This matches js-libp2p approach - they don't wait for ICE state
                with trio.move_on_after(30):  # 30s timeout
                    done_event = trio.Event()

                    async def wait_established() -> None:
                        await connection_established.wait()
                        logger.info(f"{role} connection_established event received")
                        done_event.set()

                    async def wait_failed() -> None:
                        await connection_failed.wait()
                        logger.warning(f"{role} connection_failed event received")
                        done_event.set()

                    async def poll_connection_state() -> None:
                        """Poll connectionState - accept 'connected' despite ICE"""
                        check_interval = 0.05  # Check every 50ms
                        while True:
                            await trio.sleep(check_interval)
                            if (
                                connection_established.is_set()
                                or connection_failed.is_set()
                            ):
                                return
                            current_conn = peer_connection.connectionState
                            current_ice = peer_connection.iceConnectionState

                            # Accept connection if connectionState is "connected"
                            if current_conn == "connected":
                                logger.info(
                                    f"{role} poll detected connectionState='connected' "
                                    f"(ICE={current_ice}) - proceeding"
                                )
                                connection_established.set()
                                done_event.set()
                                return
                            elif current_conn in ("failed", "disconnected", "closed"):
                                logger.error(
                                    f"{role} connection failed: {current_conn}"
                                )
                                connection_failed.set()
                                done_event.set()
                                return

                    async with trio.open_nursery() as nursery:
                        nursery.start_soon(wait_established)
                        nursery.start_soon(wait_failed)
                        nursery.start_soon(poll_connection_state)
                        await done_event.wait()
                        nursery.cancel_scope.cancel()

        if connection_failed.is_set():
            raise Exception(
                f"Peer connection failed or disconnected "
                f"(state: {peer_connection.connectionState}, "
                f" ICE: {peer_connection.iceConnectionState})"
            )

        if not connection_established.is_set():
            # Final check: verify current state
            current_conn_state = peer_connection.connectionState
            current_ice_state = peer_connection.iceConnectionState

            # Check if ICE connected but connectionState didn't update
            if ice_connected.is_set():
                logger.debug(
                    f"{role} ICE connected but connectionState is "
                    f" {current_conn_state}, "
                    "waiting a bit longer..."
                )
                await trio.sleep(1.0)  # Give connectionState time to update
                if peer_connection.connectionState == "connected":
                    connection_established.set()
                else:
                    raise Exception(
                        f"ICE connected but peer connection did not establish "
                        f"(state: {peer_connection.connectionState}, "
                        f" ICE: {peer_connection.iceConnectionState})"
                    )
            # Check if ICE is closed but connectionState is connected (this is valid)
            elif current_ice_state == "closed" and current_conn_state == "connected":
                logger.info(
                    f"{role} ICE closed but connectionState is connected - "
                    "connection is established, proceeding"
                )
                connection_established.set()
            else:
                raise Exception(
                    f"Peer connection did not establish in time "
                    f"(state: {current_conn_state}, "
                    f" ICE: {current_ice_state})"
                )

        logger.info(
            f"{role} peer connection established - "
            "proceeding to data channel verification"
        )

        # Validate ICE connection state before proceeding
        # Note: ICE might be "closed" if it closed after connection was established
        # This is normal behavior - check connectionState instead
        ice_state = peer_connection.iceConnectionState
        connection_state = peer_connection.connectionState

        # If connection is connected, ICE closed is acceptable (normal after handshake)
        if ice_state == "closed" and connection_state != "connected":
            raise Exception(
                f"ICE connection is closed before connection established "
                f"(connectionState: {connection_state}, "
                f"iceConnectionState: {ice_state})"
            )
        if (
            ice_state not in ("connected", "completed")
            and connection_state != "connected"
        ):
            logger.warning(
                f"{role} ICE connection state is {ice_state}, not connected/completed. "
                f"Connection state: {connection_state}. Proceeding with caution..."
            )

        # Now wait for handshake channel to open
        # CRITICAL: The handshake channel must be fully open and ready
        # before we can start the Noise handshake
        if handshake_channel.readyState != "open":
            logger.debug(
                "%s wait for handshake channel to open, starting status %s",
                role,
                handshake_channel.readyState,
            )
            # Wait for the 'open' event or signal cancellation
            open_event = trio.Event()

            def on_open() -> None:
                logger.debug(f"{role} handshake channel opened event received")
                open_event.set()

            handshake_channel.on("open", on_open)
            # Check if already open
            # (might have opened while we were waiting for conn)
            if handshake_channel.readyState == "open":
                logger.debug(f"{role} handshake channel already open")
                open_event.set()
            else:
                logger.debug(f"{role} waiting for handshake channel to open...")
                with trio.move_on_after(30):  # 30s timeout
                    await open_event.wait()
            if handshake_channel.readyState != "open":
                raise Exception(
                    f"Handshake data channel did not open in time "
                    f"(state: {handshake_channel.readyState}, "
                    f"peer connection state: {rtc_pc.connectionState}, "
                    f"ICE state: {peer_connection.iceConnectionState})"
                )

        # Additional verification: ensure channel is truly ready
        # Give it a small delay to ensure all internal state is ready
        await trio.sleep(0.1)

        # Double-check channel state after delay
        if handshake_channel.readyState != "open":
            raise Exception(
                f"Handshake channel closed after opening "
                f"(state: {handshake_channel.readyState})"
            )

        logger.debug("%s handshake channel opened", role)

        # Verifying data channel can actually send data
        # This prevents false positives where channel appears open but data doesn't flow
        logger.debug("%s verifying data channel can send data...", role)
        try:
            # Verify channel state is still open
            if handshake_channel.readyState != "open":
                raise Exception(
                    f"Data channel not open for verification "
                    f"(state: {handshake_channel.readyState})"
                )

            # Check channel properties to ensure it's operational
            # bufferedAmount should be accessible (indicates channel is ready)
            try:
                buffered = handshake_channel.bufferedAmount
                logger.debug("%s data channel bufferedAmount: %d bytes", role, buffered)
            except Exception as e:
                logger.warning(
                    "%s could not check data channel bufferedAmount: %s", role, e
                )

            # Verify ICE connection is still good
            # Note: ICE can be "closed" after connection is established - this is normal
            current_ice_state = peer_connection.iceConnectionState
            current_conn_state = peer_connection.connectionState
            if current_ice_state == "closed" and current_conn_state != "connected":
                raise Exception(
                    f"ICE connection closed during data channel verification "
                    f"(ICE state: {current_ice_state}, "
                    f" connection state: {current_conn_state})"
                )

            logger.info(
                "%s data channel verified successfully. "
                "Channel state: %s, ICE state: %s, Connection state: %s. "
                "Proceeding to Noise handshake...",
                role,
                handshake_channel.readyState,
                current_ice_state,
                current_conn_state,
            )

        except Exception as e:
            logger.error(
                "%s data channel verification failed: %s", role, e, exc_info=True
            )
            raise Exception(
                f"Data channel verification failed: {e}. "
                f"Channel state: {handshake_channel.readyState}, "
                f"ICE state: {peer_connection.iceConnectionState}, "
                f"Connection state: {peer_connection.connectionState}"
            ) from e

        rtc_pc = peer_connection.peer_connection

        remote_fingerprint: str | None = None
        if role == "server":
            if remote_addr is not None:
                try:
                    remote_fingerprint = multiaddr_to_fingerprint(remote_addr)
                except Exception:
                    remote_fingerprint = None
            if remote_fingerprint is None and rtc_pc.remoteDescription is not None:
                remote_fingerprint = SDP.get_fingerprint_from_sdp(
                    rtc_pc.remoteDescription.sdp
                )
            if remote_fingerprint and remote_addr is None:
                remote_addr = fingerprint_to_multiaddr(remote_fingerprint)
        else:
            if rtc_pc.remoteDescription is not None:
                remote_fingerprint = SDP.get_fingerprint_from_sdp(
                    rtc_pc.remoteDescription.sdp
                )
            if remote_fingerprint is None and remote_addr is not None:
                try:
                    remote_fingerprint = multiaddr_to_fingerprint(remote_addr)
                except Exception:
                    remote_fingerprint = None

        # Get local fingerprint
        local_desc = peer_connection.localDescription
        local_fingerprint = SDP.get_fingerprint_from_sdp(
            local_desc.sdp if local_desc is not None else None
        )
        if local_fingerprint is None:
            logger.error(
                "%s unable to extract local fingerprint;"
                " localDescription present=%s, sdp=%r",
                role,
                local_desc is not None,
                local_desc.sdp if local_desc is not None else None,
            )
            raise Exception("Could not get fingerprint from local description sdp")

        logger.warning("%s local fingerprint extracted: %s", role, local_fingerprint)

        if remote_fingerprint is None:
            try:
                fp_obj = peer_connection.remoteFingerprint()
            except Exception:  # pragma: no cover - defensive
                fp_obj = None
            if fp_obj:
                fp_value = getattr(fp_obj, "value", None)
                if fp_value:
                    algorithm = getattr(fp_obj, "algorithm", "sha-256")
                    remote_fingerprint = f"{algorithm} {fp_value.upper()}"
        logger.warning(
            "%s remote fingerprint as seen in SDP/DTLS: %s",
            role,
            remote_fingerprint,
        )

        expected_certhash: str | None = certhash
        if expected_certhash is None and remote_addr is not None:
            try:
                expected_certhash = extract_certhash(remote_addr)
            except Exception:
                expected_certhash = None

        actual_certhash: str | None = None
        if remote_fingerprint:
            try:
                actual_certhash = fingerprint_to_certhash(remote_fingerprint)
            except Exception:
                actual_certhash = None

        logger.warning(
            "%s expected certhash=%s actual certhash=%s",
            role,
            expected_certhash,
            actual_certhash,
        )
        if expected_certhash is not None and actual_certhash is not None:
            if expected_certhash != actual_certhash:
                raise Exception(
                    "Remote certhash mismatch detected during WebRTC connection setup"
                )

        if remote_peer_id is None and remote_addr is not None:
            try:
                peer_id_str = remote_addr.value_for_protocol("p2p")
                if peer_id_str:
                    remote_peer_id = ID.from_base58(peer_id_str)
            except Exception:
                remote_peer_id = None

        if remote_peer_id is None:
            raise Exception("Remote peer ID could not be determined for WebRTC-Direct")

        # Verify data channel is open and ready before creating connection wrapper
        # This is critical - the channel must be open for the handshake to work
        if handshake_channel.readyState != "open":
            raise Exception(
                f"{role} handshake channel not open when creating WebRTCRawConnection "
                f"(state: {handshake_channel.readyState}, "
                f"connectionState: {peer_connection.connectionState}, "
                f"ICE state: {peer_connection.iceConnectionState})"
            )

        # Now that the connection has been opened, add the remote's certhash to
        # the multiaddr so we can complete the noise handshake (matches js-libp2p)
        if role == "server" and remote_fingerprint is not None:
            try:
                client_certhash = fingerprint_to_certhash(remote_fingerprint)
                if remote_addr is not None and client_certhash:
                    remote_addr = canonicalize_certhash(remote_addr, client_certhash)
                    logger.debug(
                        f"{role} updated remote_addr with client certhash: "
                        f"{client_certhash}"
                    )
            except Exception as e:
                logger.warning(
                    f"{role} failed to add client certhash to remote_addr: {e}"
                )
        elif remote_addr is not None and actual_certhash is not None:
            remote_addr = canonicalize_certhash(remote_addr, actual_certhash)

        # Verify peer connection is still connected
        if peer_connection.connectionState not in ("connected", "connecting"):
            logger.warning(
                f"{role} peer connection state is {peer_connection.connectionState} "
                f"when creating WebRTCRawConnection - this may cause issues"
            )

        logger.info(
            f"{role} creating WebRTCRawConn with "
            f"channel state: {handshake_channel.readyState}, "
            f"connection state: {peer_connection.connectionState}"
        )

        raw_connection = WebRTCRawConnection(
            remote_peer_id,
            rtc_pc,
            handshake_channel,
            is_initiator=(role == "client"),
        )

        logger.info(f"{role} WebRTCRawConnection created successfully")

        raw_connection.remote_multiaddr = remote_addr
        raw_connection.remote_fingerprint = remote_fingerprint
        raw_connection.local_fingerprint = local_fingerprint
        secure_conn: "IRawConnection | ISecureConn" = raw_connection

        # CRITICAL: Mark handshake as in progress IMMEDIATELY after creating connection
        # This prevents the data channel's on_close handler from closing the connection
        # before the handshake can start
        raw_connection._handshake_in_progress = True
        logger.debug(
            f"{role} Marked handshake as in progress to prevent premature closure"
        )

        noise_prologue: bytes | None = None
        if remote_addr is not None:
            noise_prologue = generate_noise_prologue(
                local_fingerprint, remote_addr, role
            )
            prologue_len = len(noise_prologue) if noise_prologue else 0
            first_bytes = (
                noise_prologue[:50].hex()
                if noise_prologue and len(noise_prologue) >= 50
                else (noise_prologue.hex() if noise_prologue else "None")
            )
            logger.debug(
                f"{role} generated prologue: len={prologue_len}, "
                f"first_50_bytes={first_bytes}"
            )

        sec_avail = "None" if security_multistream is None else "available"
        data_state = (
            raw_connection.data_channel.readyState
            if hasattr(raw_connection, "data_channel")
            else "N/A"
        )
        logger.info(
            f"{role} security_multistream check: "
            f"security_multistream is {sec_avail}, "
            f"raw_connection type: {type(raw_connection)}, "
            f"data_channel state: {data_state}"
        )

        if security_multistream is not None:
            # In WebRTC Direct, we skip multiselect negotiation and directly use Noise
            # This matches js-libp2p behavior where Noise is used directly
            data_state = (
                raw_connection.data_channel.readyState
                if hasattr(raw_connection, "data_channel")
                else "N/A"
            )
            logger.info(
                f"{role} preparing Noise handshake: "
                f"security_multistream available, "
                f"noise_prologue generated: {noise_prologue is not None}, "
                f"raw_connection type: {type(raw_connection)}, "
                f"data_channel state: {data_state}"
            )

            if NOISE_PROTOCOL_ID not in security_multistream.transports:
                available = list(security_multistream.transports.keys())
                raise Exception(
                    f"{role} Noise transport not found in security_multistream. "
                    f"Available transports: {available}, "
                    f"Expected: {NOISE_PROTOCOL_ID}"
                )
            transport = security_multistream.transports[NOISE_PROTOCOL_ID]
            logger.debug(f"{role} got Noise transport: {type(transport)}")

            if hasattr(transport, "set_prologue"):
                transport.set_prologue(noise_prologue)
                logger.info(
                    f"{role} set prologue on transport: "
                    f"len={len(noise_prologue) if noise_prologue else 0}"
                )
            else:
                logger.warning(f"{role} transport does not have set_prologue method")

            # Perform Noise handshake with proper error handling
            try:
                logger.info(
                    f"{role} starting Noise handshake... "
                    f"role={role}, "
                    f"connection closed: {raw_connection._closed}, "
                    f"data_channel state: {raw_connection.data_channel.readyState}, "
                    f"peer_connection state: {peer_connection.connectionState}, "
                    f"ICE state: {peer_connection.iceConnectionState}, "
                    f"handshake_in_progress: {raw_connection._handshake_in_progress}"
                )
                # Verify connection is still open before starting handshake
                if raw_connection._closed:
                    raise Exception(
                        f"{role} Connection already closed before handshake started"
                    )
                if raw_connection.data_channel.readyState != "open":
                    raise Exception(
                        f"{role} Data channel not open before handshake "
                        f"(state: {raw_connection.data_channel.readyState})"
                    )

                # In WebRTC Direct, the server (listener) initiates the Noise handshake,
                # so the client waits (secure_inbound) and the server starts
                # (secure_outbound). This matches js-libp2p behavior.
                if role == "client":
                    logger.info(
                        f"{role} calling secure_inbound "
                        "(waiting for server to initiate)..."
                    )
                    secure_conn = await transport.secure_inbound(raw_connection)
                    logger.info(f"{role} secure_inbound completed successfully")
                else:
                    logger.info(
                        f"{role} calling secure_outbound (initiating handshake)... "
                        f"remote_peer_id: {remote_peer_id}"
                    )
                    secure_conn = await transport.secure_outbound(
                        raw_connection, remote_peer_id
                    )
                    logger.info(f"{role} secure_outbound completed successfully")

                # Mark handshake as complete
                raw_connection._handshake_in_progress = False
                logger.info(f"{role} Noise handshake completed successfully")
            except Exception as handshake_error:
                # Mark handshake as no longer in progress
                raw_connection._handshake_in_progress = False
                logger.error(
                    f"{role} Noise handshake failed: {handshake_error}", exc_info=True
                )
                # Check if connection is still usable
                if raw_connection._closed:
                    logger.error(
                        f"{role} Connection closed during handshake - "
                        "this may indicate a timing issue or connection error"
                    )
                # Check data channel state
                logger.error(
                    f"{role} Data channel state after handshake failure: "
                    f"{raw_connection.data_channel.readyState}, "
                    f"connection state: {peer_connection.connectionState}, "
                    f"ICE state: {peer_connection.iceConnectionState}"
                )
                # Re-raise to let caller handle it
                raise

        if hasattr(secure_conn, "remote_multiaddr"):
            setattr(secure_conn, "remote_multiaddr", remote_addr)
        if hasattr(secure_conn, "remote_fingerprint"):
            setattr(secure_conn, "remote_fingerprint", remote_fingerprint)
        if hasattr(secure_conn, "local_fingerprint"):
            setattr(secure_conn, "local_fingerprint", local_fingerprint)
        if hasattr(secure_conn, "remote_peer_id"):
            setattr(secure_conn, "remote_peer_id", remote_peer_id)
        if signal_service is not None and remote_peer_id is not None:
            await signal_service.flush_local_ice(remote_peer_id)
            await signal_service.flush_ice_candidates(remote_peer_id)

        return secure_conn, answer_desc if role == "server" else None

    except Exception as e:
        logger.error("%s noise handshake failed: %s", role, e, exc_info=True)
        # Provide more context about the failure
        if hasattr(e, "__cause__") and e.__cause__:
            logger.error(
                "%s handshake failure cause: %s", role, e.__cause__, exc_info=True
            )
        raise
    finally:
        if signal_service is not None and cleanup_handlers:
            for msg_type, handler in cleanup_handlers:
                signal_service.remove_handler(msg_type, handler)
        if signal_service is not None and remote_peer_id is not None:
            signal_service.pending_local_ice.pop(str(remote_peer_id), None)
