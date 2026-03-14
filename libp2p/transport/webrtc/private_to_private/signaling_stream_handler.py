import logging
import sys
from typing import Any

from aiortc import (
    RTCConfiguration,
    RTCDataChannel,
    RTCPeerConnection,
    RTCSessionDescription,
)
import trio
from trio_asyncio import aio_as_trio

if sys.version_info >= (3, 11):
    pass
else:
    pass

import json

from aioice.candidate import Candidate
from aiortc.rtcicetransport import candidate_from_aioice

from libp2p.abc import INetStream, IRawConnection
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.utils.varint import encode_uvarint, read_length_prefixed_protobuf

from ..aiortc_patch import (
    get_dtls_state,
    get_sctp_state,
    is_dtls_connected,
    is_handshake_active,
    is_sctp_connected,
    register_handshake,
    unregister_handshake,
)
from ..async_bridge import TrioSafeWebRTCOperations
from ..connection import WebRTCRawConnection
from ..constants import WebRTCError
from .pb import Message

logger = logging.getLogger("webrtc.private.signaling_stream_handler")


async def handle_incoming_stream(
    stream: INetStream,
    rtc_config: RTCConfiguration,
    connection_info: dict[str, Any] | None,
    host: Any,
    timeout: float = 30.0,
) -> IRawConnection | None:
    """
    Handle incoming signaling stream for WebRTC connection.

    This function acts as the "answerer" in the WebRTC handshake:
    1. Receives SDP offer from remote peer over signaling stream
    2. Creates SDP answer with ICE candidates
    3. Sends answer back to remote peer
    4. Waits for data channel to be established
    5. Returns WebRTC connection with ED25519 peer ID
    """
    logger.info("Handling incoming signaling stream for WebRTC connection")

    peer_connection = None
    received_data_channel = None

    try:
        # Create peer connection
        peer_connection = RTCPeerConnection(rtc_config)

        # CRITICAL: Create negotiated init channel BEFORE setRemoteDescription
        # This matches the initiator's init channel (negotiated=True, id=0)
        # Both sides must create this with same parameters for it to open reliably
        init_channel = peer_connection.createDataChannel("init", negotiated=True, id=0)
        logger.debug(
            f"Created negotiated init channel on answerer "
            f"(id=0, state={init_channel.readyState})"
        )

        # Create incoming message buffer early to prevent message loss
        # This must be created before any channels are received
        message_buffer_send, message_buffer_recv = trio.open_memory_channel(1000)

        def _early_message_handler(message: Any) -> None:
            """Early handler that buffers all messages immediately to prevent loss."""
            try:
                if hasattr(message, "data"):
                    data = message.data
                    if isinstance(data, bytes):
                        pass
                    elif hasattr(data, "tobytes"):
                        data = data.tobytes()
                    else:
                        data = bytes(data) if data else b""
                elif isinstance(message, bytes):
                    data = message
                else:
                    try:
                        data = bytes(message)
                    except (TypeError, ValueError):
                        data = str(message).encode()

                if data:
                    try:
                        message_buffer_send.send_nowait(data)
                        logger.debug(
                            f"Answerer early handler buffered {len(data)} bytes"
                        )
                    except trio.WouldBlock:
                        logger.warning("Message buffer full, dropping message")
                    except trio.ClosedResourceError:
                        logger.debug("Message buffer closed")
            except Exception as e:
                logger.debug(f"Error in early message handler: {e}")

        # Create events for coordination
        data_channel_received = trio.Event()
        connection_failed = trio.Event()

        def on_data_channel(channel: RTCDataChannel) -> None:
            """Handle incoming data channel from initiator"""
            nonlocal received_data_channel
            channel_id = getattr(channel, "id", "N/A")
            logger.info(
                f"🔔🔔🔔 datachannel event FIRED! Received channel from initiator: "
                f"label='{channel.label}', state={channel.readyState}, id={channel_id}"
            )

            # CRITICAL: Ignore the negotiated "init" channel (id=0)
            # Since we created it as negotiated=True, id=0, we should NOT receive it
            # via datachannel event. If we do, it's a duplicate and should be ignored.
            if channel.label == "init" or channel_id == 0:
                logger.debug(
                    "Ignoring init channel received via datachannel event "
                    "(we created it as negotiated, id=0)"
                )
                return

            # This is the application data channel from initiator
            received_data_channel = channel
            # Attach early handler immediately when channel is received
            channel.on("message", _early_message_handler)
            logger.debug("Attached early message handler to received data channel")
            data_channel_received.set()
            logger.info(
                f"✅ Set data_channel_received event "
                f"(channel label: '{channel.label}', "
                f"state: {channel.readyState}, id={channel_id})"
            )

        # Register data channel handler BEFORE setting remote description
        # This ensures we catch the channel when it arrives
        peer_connection.on("datachannel", on_data_channel)
        logger.debug(
            "✅ Registered datachannel event handler (will catch all incoming channels)"
        )

        # Also log when datachannel event might fire
        def log_datachannel_event(*args: Any, **kwargs: Any) -> None:
            kwargs_keys = list(kwargs.keys())
            logger.info(
                f"🔔 datachannel event callback invoked with "
                f"args={len(args)}, kwargs={kwargs_keys}"
            )

        # Note: We can't easily wrap the event, but on_data_channel will log when called

        # Read varint-prefixed offer from signaling stream
        try:
            # Check stream state before reading
            if hasattr(stream, "is_closed") and stream.is_closed():
                raise WebRTCError("Signaling stream is closed before reading offer")

            # Read with timeout to prevent hanging
            with trio.move_on_after(30.0) as timeout_scope:
                offer_data = await read_length_prefixed_protobuf(
                    stream, use_varint_format=True, max_length=1024 * 1024
                )

            if timeout_scope.cancelled_caught:
                raise WebRTCError("Timeout reading offer from signaling stream (30s)")

            if not offer_data:
                raise WebRTCError("No offer data received (empty response)")

            offer_message = Message()
            try:
                offer_message.ParseFromString(offer_data)
            except Exception as parse_error:
                raise WebRTCError(
                    f"Failed to parse offer protobuf: {parse_error} "
                    f"(received {len(offer_data)} bytes)"
                ) from parse_error

            if offer_message.type != Message.SDP_OFFER:
                raise WebRTCError(
                    f"Expected SDP_OFFER, got message type: {offer_message.type}"
                )

            if not offer_message.data:
                raise WebRTCError("Offer message has no SDP data")

            offer = RTCSessionDescription(sdp=offer_message.data, type="offer")

            logger.info(f"Received SDP offer ({len(offer_data)} bytes)")

        except WebRTCError:
            raise
        except Exception as e:
            error_type = type(e).__name__
            raise WebRTCError(
                f"Failed to receive or parse offer: {error_type}: {e}"
            ) from e

        # Set remote description
        # Note: We're already in an open_loop()
        #  context (from transport listener),
        # so use aio_as_trio directly
        await aio_as_trio(peer_connection.setRemoteDescription(offer))
        logger.debug("Set remote description from offer")

        # Create and set local description (answer)
        answer = await aio_as_trio(peer_connection.createAnswer())
        if answer is None:
            raise WebRTCError("Failed to create SDP answer")
        await aio_as_trio(peer_connection.setLocalDescription(answer))
        logger.info("Created and set local description (answer)")

        # Send varint-prefixed answer back
        try:
            answer_message = Message()
            answer_message.type = Message.SDP_ANSWER
            answer_message.data = answer.sdp
            answer_bytes = answer_message.SerializeToString()
            # Per spec: prefix with varint length
            varint_prefix = encode_uvarint(len(answer_bytes))
            logger.debug(f"Sending SDP answer ({len(answer_bytes)} bytes)")
            await stream.write(varint_prefix + answer_bytes)
            logger.info("Sent SDP answer successfully")

        except Exception as e:
            logger.error(f"Failed to send answer: {e}", exc_info=True)
            raise WebRTCError(f"Failed to send answer: {e}") from e

        # Send ICE candidates from answer SDP
        logger.debug("Sending ICE candidates from answer")
        await _send_ice_candidates(stream, peer_connection)

        # Read incoming ICE candidates until connected
        logger.debug("Reading incoming ICE candidates until connected")
        await _read_candidates_until_connected(stream, peer_connection, timeout)

        # Verify connection is established
        # NOTE: Do NOT close signaling stream here - keep it open until after
        # we receive the new application data channel. The initiator needs
        # the stream to stay open until after it closes init channel and creates
        # the new channel. We'll close it at the end, after receiving the channel.
        # CRITICAL: We need BOTH connectionState AND ICE to be ready for SCTP to work
        connection_established = trio.Event()
        ice_connected = trio.Event()
        connection_failed = trio.Event()

        def on_connection_state_change() -> None:
            if peer_connection is not None:
                state = peer_connection.connectionState
                logger.debug(f"Connection state: {state}")
                if state == "connected":
                    connection_established.set()
                elif state == "failed":
                    connection_failed.set()

        def on_ice_connection_state_change() -> None:
            if peer_connection is not None:
                ice_state = peer_connection.iceConnectionState
                logger.debug(f"ICE connection state: {ice_state}")
                if ice_state in ("connected", "completed"):
                    ice_connected.set()
                elif ice_state == "failed":
                    connection_failed.set()

        # Register both connection and ICE state handlers
        peer_connection.on("connectionstatechange", on_connection_state_change)
        peer_connection.on("iceconnectionstatechange", on_ice_connection_state_change)

        # Check current states
        current_conn_state = peer_connection.connectionState
        current_ice_state = peer_connection.iceConnectionState

        logger.debug(
            f"Initial states: connectionState={current_conn_state}, "
            f"iceConnectionState={current_ice_state}"
        )

        if current_conn_state == "connected":
            connection_established.set()
        elif current_conn_state == "failed":
            connection_failed.set()

        if current_ice_state in ("connected", "completed"):
            ice_connected.set()
        elif current_ice_state == "failed":
            connection_failed.set()

        # Wait for BOTH connection and ICE to be ready
        # This is critical for SCTP to establish properly
        if not connection_established.is_set() or not ice_connected.is_set():
            logger.debug("Waiting for connection and ICE to be ready...")
            with trio.move_on_after(30.0) as conn_scope:
                # Wait for connection state
                if not connection_established.is_set():
                    await connection_established.wait()
                # Wait for ICE state
                if not ice_connected.is_set():
                    await ice_connected.wait()
            if conn_scope.cancelled_caught:
                final_conn_state = peer_connection.connectionState
                final_ice_state = peer_connection.iceConnectionState
                logger.warning(
                    f"Connection/ICE not ready within timeout: "
                    f"connectionState={final_conn_state}, "
                    f"iceConnectionState={final_ice_state}"
                )
                # If connection is connected but ICE isn't, we might still proceed
                if final_conn_state != "connected":
                    raise WebRTCError(
                        f"Connection not established (state: {final_conn_state}, "
                        f"ICE: {final_ice_state})"
                    )
                elif final_ice_state not in ("connected", "completed", "closed"):
                    logger.warning(
                        f"ICE not fully ready (state: {final_ice_state}), "
                        "but connection is connected - proceeding with caution"
                    )

        if connection_failed.is_set():
            raise WebRTCError("WebRTC connection failed")

        logger.info(
            f"WebRTC connection established successfully "
            f"(connectionState={peer_connection.connectionState}, "
            f"iceConnectionState={peer_connection.iceConnectionState})"
        )

        # The answerer receives the "init" data channel from the initiator.
        # Per spec: The "init" channel is closed by the initiator
        # after connection.
        # We receive it, close it, then wait for the initiator to create
        # a new application data channel (which we receive via datachannel event).

        # Wait briefly for "init" channel (if not already received) -
        # it will be closed by initiator
        if not received_data_channel:
            logger.debug(
                "Waiting for 'init' data channel from initiator "
                "(will be closed by initiator)..."
            )
            with trio.move_on_after(5.0) as channel_scope:
                await data_channel_received.wait()
            if channel_scope.cancelled_caught:
                logger.debug(
                    "No 'init' channel received "
                    "(may have been closed already by initiator)"
                )

        if received_data_channel and received_data_channel.label == "init":
            logger.debug("Closing received 'init' channel per spec")
            try:
                # Use bridge to close data channel properly
                bridge = TrioSafeWebRTCOperations._get_bridge()
                await bridge.close_data_channel(received_data_channel)
            except Exception as e:
                logger.debug(f"Error closing received init channel: {e}")
            # Clear the received_data_channel so we wait for the new one
            received_data_channel = None
            data_channel_received = trio.Event()

        # CRITICAL: Only initiator should create the application data channel.
        # Answerer waits for incoming channel from initiator (per WebRTC spec).
        logger.debug("Waiting for incoming application data channel from initiator...")
        has_received_channel = received_data_channel is not None
        channel_received_set = data_channel_received.is_set()
        logger.debug(
            f"Current state: received_data_channel={has_received_channel}, "
            f"data_channel_received.is_set()={channel_received_set}"
        )
        if received_data_channel is None:
            # Wait for the initiator to create and send the new data channel
            # The initiator:
            # 1) waits for init channel to open (up to 60s),
            # 2) closes init channel,
            # 3) waits for init channel to close,
            # 4) creates new channel
            # Using 90s for init channel wait + new channel creation
            with trio.move_on_after(90.0) as new_dc_scope:
                await data_channel_received.wait()
            if new_dc_scope.cancelled_caught:
                conn_state = peer_connection.connectionState
                ice_state = peer_connection.iceConnectionState
                logger.error(
                    f"⏰ Timeout waiting for application data channel! "
                    f"conn_state={conn_state}, ice_state={ice_state}, "
                    f"received_data_channel={has_received_channel}"
                )
                raise WebRTCError(
                    f"No application data channel received from initiator "
                    f"within timeout (conn_state: {conn_state}, "
                    f"ice_state: {ice_state})"
                )

        # Verify we received a channel (not the init channel)
        if received_data_channel is None:
            raise WebRTCError("No data channel received from initiator")

        if received_data_channel.label == "init":
            raise WebRTCError(
                "Received 'init' channel instead of application channel - "
                "initiator may not have created new channel yet"
            )

        logger.info(
            f"Received application data channel from initiator: "
            f"label='{received_data_channel.label}', "
            f"state={received_data_channel.readyState}"
        )

        # Wait for the received channel to open
        if received_data_channel.readyState != "open":
            current_state = received_data_channel.readyState
            logger.debug(
                f"Waiting for received data channel to open "
                f"(current state: {current_state})..."
            )
            channel_open_event = trio.Event()

            def on_channel_open() -> None:
                logger.info("Received data channel opened")
                channel_open_event.set()

            received_data_channel.on("open", on_channel_open)

            with trio.move_on_after(15.0) as open_scope:
                await channel_open_event.wait()
            if open_scope.cancelled_caught:
                conn_state = peer_connection.connectionState
                ice_state = peer_connection.iceConnectionState
                logger.warning(
                    f"Received data channel did not open within timeout "
                    f"(state: {received_data_channel.readyState}, "
                    f"conn_state: {conn_state}, ice_state: {ice_state})"
                )
                if conn_state == "connected" and ice_state in (
                    "connected",
                    "completed",
                ):
                    logger.info(
                        "Connection is stable, proceeding despite channel "
                        "not being open yet"
                    )
                else:
                    raise WebRTCError(
                        f"Received data channel failed to open and "
                        f"connection is not stable "
                        f"(conn_state: {conn_state}, ice_state: {ice_state})"
                    )

        # Extract peer ID from connection info or stream
        if connection_info and "peer_id" in connection_info:
            remote_peer_id = connection_info["peer_id"]
        elif hasattr(stream, "muxed_conn") and hasattr(stream.muxed_conn, "peer_id"):
            remote_peer_id = stream.muxed_conn.peer_id
        else:
            # Fallback - generate ED25519 peer ID for testing/compatibility
            logger.warning(
                "Could not extract remote peer ID, generating ED25519 fallback"
            )
            # Generate ED25519 key pair
            key_pair = create_new_key_pair()
            remote_peer_id = ID.from_pubkey(key_pair.public_key)

        # Early handler is already attached in on_data_channel callback above
        # Message buffer is already created above

        # CRITICAL: Verify data channel is still open before creating connection
        # The channel must be open for security upgrade to work
        if received_data_channel.readyState != "open":
            raise WebRTCError(
                f"Data channel is not open when creating connection "
                f"(state: {received_data_channel.readyState}, "
                f"conn_state: {peer_connection.connectionState}, "
                f"ice_state: {peer_connection.iceConnectionState})"
            )

        # Create WebRTC connection wrapper with ED25519 peer ID and message buffer
        webrtc_connection = WebRTCRawConnection(
            remote_peer_id,
            peer_connection,
            received_data_channel,
            is_initiator=False,  # This is the answerer
            incoming_message_buffer=message_buffer_recv,
        )

        logger.info(
            f"WebRTC connection established with ED25519 peer: {remote_peer_id} "
            f"(channel state: {received_data_channel.readyState}, "
            f"conn_state: {peer_connection.connectionState})"
        )

        # CRITICAL: Ensure data pump is ready before returning connection.
        # The answerer's upgrade_security will call read() for Noise handshake;
        # messages must flow from data channel -> pump -> read(). Without this
        # wait, upgrade can time out before first dialer messages are buffered.
        await webrtc_connection.start_buffer_consumer_async()
        await trio.sleep(0.1)

        # CRITICAL: Verify connection is still stable after creating WebRTCRawConnection
        if peer_connection.connectionState == "closed":
            raise WebRTCError(
                "Peer connection closed immediately after creating WebRTCRawConnection"
            )

        if received_data_channel.readyState != "open":
            raise WebRTCError(
                f"Data channel closed immediately after creating WebRTCRawConnection "
                f"(state: {received_data_channel.readyState})"
            )

        # CRITICAL: Verify DTLS and SCTP states before returning connection
        # Wait for DTLS to connect (with timeout)
        # DTLS handshake happens after ICE completes, so we need to wait
        dtls_connected = False
        max_dtls_wait = 10.0  # Wait up to 10 seconds for DTLS (more generous)
        start_time = trio.current_time()
        dtls_state = None

        while trio.current_time() - start_time < max_dtls_wait:
            dtls_state = get_dtls_state(peer_connection)
            if dtls_state is not None:
                if is_dtls_connected(peer_connection):
                    dtls_connected = True
                    break
                # If DTLS state is available but not connected, log and continue waiting
                if dtls_state in ("closed", "failed"):
                    logger.error(
                        f"DTLS in terminal state: {dtls_state}, "
                        f"connectionState={peer_connection.connectionState}, "
                        f"iceConnectionState={peer_connection.iceConnectionState}"
                    )
                    raise WebRTCError(
                        f"DTLS transport in terminal state: {dtls_state} - "
                        "cannot proceed with connection"
                    )
            await trio.sleep(0.2)

        if not dtls_connected:
            final_dtls_state = get_dtls_state(peer_connection)
            logger.error(
                f"DTLS not connected after {max_dtls_wait}s: state={final_dtls_state}, "
                f"connectionState={peer_connection.connectionState}, "
                f"iceConnectionState={peer_connection.iceConnectionState}"
            )
            if final_dtls_state is None:
                logger.warning(
                    "DTLS state unavailable - proceeding anyway "
                    "(may be aiortc version compatibility issue)"
                )
            else:
                raise WebRTCError(
                    f"DTLS transport not connected (state: {final_dtls_state}) - "
                    "cannot proceed with connection"
                )

        # Verify SCTP is connected
        sctp_state = get_sctp_state(peer_connection)
        if sctp_state is not None and not is_sctp_connected(peer_connection):
            logger.error(
                f"SCTP not connected: state={sctp_state}, "
                f"connectionState={peer_connection.connectionState}, "
                f"iceConnectionState={peer_connection.iceConnectionState}"
            )
            raise WebRTCError(
                f"SCTP transport not connected (state: {sctp_state}) - "
                "cannot proceed with connection"
            )

        final_dtls_state = get_dtls_state(peer_connection)
        final_sctp_state = get_sctp_state(peer_connection)
        logger.info(
            f"DTLS and SCTP verified before returning connection: "
            f"DTLS={final_dtls_state}, SCTP={final_sctp_state}"
        )

        # CRITICAL: Register handshake RIGHT BEFORE RETURNING
        # This ensures it's only registered if connection is stable and ready
        # The handshake will be active during security upgrade
        register_handshake(peer_connection)
        logger.debug(
            f"Registered handshake for peer connection {id(peer_connection)} "
            f"(connection stable, DTLS/SCTP ready, ready for security upgrade)"
        )

        # Close signaling stream(after receiving new channel)
        logger.debug("Closing signaling stream")
        try:
            await stream.close()
        except Exception as e:
            logger.warning(f"Error closing signaling stream: {e}")

        return webrtc_connection

    except Exception as e:
        logger.error(f"Failed to handle incoming signaling stream: {e}")

        # CRITICAL: Unregister handshake if it was registered
        # This prevents "SCTP closing while handshakes exist" warnings
        if peer_connection:
            unregister_handshake(peer_connection)
            try:
                await aio_as_trio(peer_connection.close())
            except Exception as cleanup_error:
                logger.warning(f"Error during cleanup: {cleanup_error}")
        return None


async def _send_signaling_message(stream: INetStream, message: Message) -> None:
    """Send a signaling message over the stream with varint length prefix."""
    try:
        # Per spec: Messages are sent prefixed with the message length in bytes,
        # encoded as an unsigned variable length integer
        message_bytes = message.SerializeToString()
        varint_prefix = encode_uvarint(len(message_bytes))
        await stream.write(varint_prefix + message_bytes)
        logger.debug(
            f"Sent signaling message: {message.type} ({len(message_bytes)} bytes)"
        )
    except Exception as e:
        logger.error(f"Failed to send signaling message: {e}")
        raise


async def _receive_signaling_message(stream: INetStream, timeout: float) -> Message:
    """
    Receive a varint-prefixed signaling message from the stream.

    NOTE: This function does NOT use cancel scopes to avoid nested scope issues.
    The caller should manage timeouts at a higher level.
    """
    try:
        # Read varint-prefixed protobuf message per spec
        message_data = await read_length_prefixed_protobuf(
            stream, use_varint_format=True, max_length=1024 * 1024
        )

        # Parse protobuf message
        deserialized_msg = Message()
        deserialized_msg.ParseFromString(message_data)
        msg_type = deserialized_msg.type
        msg_len = len(message_data)
        logger.debug(f"Received signaling message: {msg_type} ({msg_len} bytes)")
        return deserialized_msg

    except WebRTCError:
        # Re-raise WebRTCErrors as-is
        raise
    except Exception as e:
        logger.error(f"Failed to receive signaling message: {e}")
        raise WebRTCError(f"Failed to receive signaling message: {e}") from e


async def _send_ice_candidates(
    stream: INetStream, peer_connection: RTCPeerConnection
) -> None:
    """Extract and send ICE candidates from local description SDP."""
    # Get SDP from localDescription to extract ICE Candidate
    sdp = peer_connection.localDescription.sdp
    sdp_lines = sdp.splitlines()

    # Find media lines (m=) to determine sdpMLineIndex for candidates
    mline_index = 0
    msg = Message()
    msg.type = Message.ICE_CANDIDATE

    # Extract ICE_Candidate and send each separately
    for line in sdp_lines:
        if line.startswith("m="):
            # New media line - increment index
            mline_index += 1
        elif line.startswith("a=candidate:"):
            cand_str = line[len("a=") :]
            # Use the current m-line index
            # (0-indexed in WebRTC, but we track 1-indexed)
            # WebRTC uses 0-indexed, so subtract 1
            candidate_init = {
                "candidate": cand_str,
                "sdpMLineIndex": max(0, mline_index - 1),
            }
            data = json.dumps(candidate_init)
            msg.data = data
            await _send_signaling_message(stream, msg)
            logger.debug("Sent ICE candidate init: %s", candidate_init)

    # Mark end-of-candidates
    msg = Message(type=Message.ICE_CANDIDATE, data=json.dumps(None))
    await _send_signaling_message(stream, msg)
    logger.debug("Sent end-of-ICE marker")


async def _read_candidates_until_connected(
    stream: INetStream, peer_connection: RTCPeerConnection, timeout: float
) -> None:
    """
    Read ICE candidates until connection is established.

    NOTE: This function does NOT use nested cancel scopes to avoid Trio corruption.
    It uses a single timeout check and connection state monitoring.
    """
    logger.debug("Reading ICE candidates until connected")

    connection_established = trio.Event()

    def on_connection_state_change() -> None:
        state = peer_connection.connectionState
        logger.debug(f"Connection state changed: {state}")
        if state == "connected":
            connection_established.set()
        elif state in ("failed", "disconnected", "closed"):
            # CRITICAL: Don't close connection if handshake is registered
            # The aiortc patch will handle this, but we should log it

            handshake_active = is_handshake_active(peer_connection)
            if handshake_active:
                logger.warning(
                    f"Connection state became {state} but handshake is active - "
                    "aiortc patch should prevent closure"
                )
            else:
                logger.warning(f"Connection state became {state}")

    # Register connection state handler
    peer_connection.on("connectionstatechange", on_connection_state_change)

    # Check if already connected
    if peer_connection.connectionState == "connected":
        logger.debug("Already connected, skipping ICE candidate reading")
        return

    # Use a single timeout for the entire operation (avoid nested cancel scopes)
    start_time = trio.current_time()

    # Read candidates until connected or timeout
    while True:
        elapsed = trio.current_time() - start_time
        if elapsed >= timeout:
            if not connection_established.is_set():
                logger.warning(
                    "Timeout reading ICE candidates, but connection not established"
                )
            else:
                logger.debug("Timeout reached but connection was established")
            break

        # Check if connection was established
        if connection_established.is_set():
            logger.debug("Connection established, stopping ICE candidate reading")
            break

        remaining_timeout = timeout - elapsed
        if remaining_timeout <= 0:
            break

        try:
            # Read next candidate message
            # Use a short timeout per read to allow connection check
            read_timeout = min(remaining_timeout, 1.0)  # Read in 1s chunks

            # Wrap the read with a timeout using move_on_after at this level only
            # (not nested since we're managing timeout with time-based checks)
            with trio.move_on_after(read_timeout) as read_scope:
                message = await _receive_signaling_message(stream, read_timeout)

            if read_scope.cancelled_caught:
                # Timeout on this read - check overall timeout
                elapsed = trio.current_time() - start_time
                if elapsed >= timeout:
                    logger.warning(
                        "Overall timeout reached during ICE candidate reading"
                    )
                    break
                # Otherwise, continue to next iteration to check connection state
                continue

            if message.type != Message.ICE_CANDIDATE:
                logger.error(f"Expected ICE candidate, got: {message.type}")
                raise WebRTCError("ICE candidate message expected")

            # Parse candidate
            try:
                candidate_init = json.loads(message.data)
            except json.JSONDecodeError:
                logger.error(f"Invalid ICE candidate JSON: {message.data}")
                continue

            # None or empty string means end-of-candidates
            if candidate_init is None or candidate_init == "":
                logger.debug("Received end-of-ICE-candidates signal")
                # Continue reading in case more candidates arrive
                continue

            # Add ICE candidate
            logger.debug(f"Received ICE candidate: {candidate_init}")
            try:
                # Ensure candidate has required fields
                if (
                    not isinstance(candidate_init, dict)
                    or "candidate" not in candidate_init
                ):
                    logger.warning(f"Invalid candidate format: {candidate_init}")
                    continue

                # Ensure sdpMLineIndex is present
                if "sdpMLineIndex" not in candidate_init:
                    candidate_init["sdpMLineIndex"] = 0

                candidate = candidate_from_aioice(
                    Candidate.from_sdp(candidate_init["candidate"])
                )
                # CRITICAL: Set sdpMLineIndex and sdpMid - aiortc requires these!
                mline_index = candidate_init.get("sdpMLineIndex", 0)
                if hasattr(candidate, "sdpMLineIndex"):
                    candidate.sdpMLineIndex = mline_index
                if not hasattr(candidate, "sdpMid") or candidate.sdpMid is None:
                    candidate.sdpMid = str(mline_index)

                try:
                    await aio_as_trio(peer_connection.addIceCandidate(candidate))
                    logger.debug("Added ICE candidate successfully")
                except Exception as e:
                    logger.warning(f"Failed to add ICE candidate: {e}")
                    # Continue reading other candidates
                    continue
            except Exception as e:
                logger.warning(f"Failed to add ICE candidate: {e}")
                # Continue reading other candidates
                continue

        except WebRTCError as e:
            # If connection is established, ignore errors
            if connection_established.is_set():
                logger.debug(f"Connection established, ignoring error: {e}")
                break
            # Check timeout before raising
            elapsed = trio.current_time() - start_time
            if elapsed >= timeout:
                logger.warning("Timeout during ICE candidate reading")
                break
            raise
        except Exception as e:
            # If connection is established, ignore errors
            if connection_established.is_set():
                logger.debug(f"Connection established, ignoring error: {e}")
                break
            # Check timeout before continuing
            elapsed = trio.current_time() - start_time
            if elapsed >= timeout:
                logger.warning("Timeout during ICE candidate reading")
                break
            logger.warning(f"Error reading ICE candidates: {e}")
            # Continue trying to read
            continue
