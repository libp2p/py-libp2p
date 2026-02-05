import json
import logging
import sys
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

if sys.version_info >= (3, 11):
    pass
else:
    pass

from trio_asyncio import aio_as_trio

from libp2p.abc import IHost, INetStream, IRawConnection
from libp2p.utils.varint import encode_uvarint, read_length_prefixed_protobuf

from ..aiortc_patch import (
    get_dtls_state,
    get_sctp_state,
    is_dtls_connected,
    is_sctp_connected,
    register_handshake,
)
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
        # dial circuit address, then open signaling stream

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

        # Create RTCPeerConnection and "init" data channel
        # CRITICAL: Use negotiated=True with fixed id=0 for init channel
        # This ensures both sides create the same channel and it opens reliably
        # The init channel is used to ensure ICE information is shared in SDP offer
        # This channel will be closed after connection is established
        # Note: We're already in an open_loop() context from transport.dial(),
        # so we can create the peer connection directly
        bridge = TrioSafeWebRTCOperations._get_bridge()
        peer_connection = await bridge.create_peer_connection(rtc_config)
        # Create negotiated init channel with fixed ID 0
        # Both initiator and answerer must create this with same parameters
        init_channel = peer_connection.createDataChannel("init", negotiated=True, id=0)
        logger.info(
            f"Created RTCPeerConnection and negotiated 'init' data channel "
            f"(id=0, state={init_channel.readyState})"
        )

        # Setup init channel ready event
        init_channel_ready = trio.Event()
        init_channel_closed = trio.Event()

        def on_init_channel_open() -> None:
            logger.info("Init data channel opened")
            init_channel_ready.set()

        def on_init_channel_close() -> None:
            logger.info("Init data channel closed")
            init_channel_closed.set()

        def on_init_channel_error(error: Any) -> None:
            logger.error(f"Init data channel error: {error}")

        init_channel.on("open", on_init_channel_open)
        init_channel.on("close", on_init_channel_close)
        init_channel.on("error", on_init_channel_error)

        # Create and send SDP offer
        # Note: We're already in an open_loop() context from transport.dial(),
        # so we use aio_as_trio directly instead of creating another bridge context
        offer = await aio_as_trio(peer_connection.createOffer())
        await aio_as_trio(peer_connection.setLocalDescription(offer))

        # Wait for ICE gathering to complete (with separate timeout)
        # Use a shorter timeout for ICE gathering so we have time for ans
        # Use 1/3 of total timeout or 10s, whichever is smaller
        ice_gathering_timeout = min(timeout / 3, 10.0)
        ice_gathering_complete = False
        with trio.move_on_after(ice_gathering_timeout):
            while peer_connection.iceGatheringState != "complete":
                await trio.sleep(0.05)
            ice_gathering_complete = True

        if not ice_gathering_complete:
            logger.warning(
                f"ICE gathering did not complete within {ice_gathering_timeout}s, "
                "proceeding with available candidates"
            )

        logger.debug("Sending SDP offer to peer as initiator")
        # Send offer
        offer_msg = Message()
        offer_msg.type = Message.SDP_OFFER
        offer_msg.data = offer.sdp
        await _send_signaling_message(signaling_stream, offer_msg)
        logger.debug("Sent SDP offer to %s", target_peer_id)

        # Wait for answer BEFORE sending ICE candidates
        logger.debug("Awaiting SDP answer from %s", target_peer_id)
        # Use remaining timeout for answer
        # (subtract time used for ICE gathering)
        answer_timeout = timeout - ice_gathering_timeout
        if answer_timeout < 5.0:
            answer_timeout = 5.0  # Min 5 sec for ans
        # Wrap with timeout at this level
        with trio.move_on_after(answer_timeout) as answer_scope:
            answer_msg = await _receive_signaling_message(
                signaling_stream, answer_timeout
            )

        if answer_scope.cancelled_caught:
            raise WebRTCError(
                f"Timeout waiting for SDP answer (timeout={answer_timeout}s)"
            )
        if answer_msg.type != Message.SDP_ANSWER:
            raise SDPHandshakeError(f"Expected answer, got: {answer_msg.type}")

        # Set remote description first (matches js-libp2p order)
        answer = RTCSessionDescription(sdp=answer_msg.data, type="answer")
        await aio_as_trio(peer_connection.setRemoteDescription(answer))

        logger.info("Set remote description from answer")

        # (Note: aiortc does not emit ice candidate event, per candidate
        # but sends it along SDP.
        # To maintain interop, we extract and resend in given format)
        # Send ICE candidates after setting remote description
        logger.debug("Sending ICE candidates to %s", target_peer_id)
        await _send_ice_candidates(signaling_stream, peer_connection)

        # Handle incoming ICE candidates
        logger.debug("Handling incoming ICE candidates from %s", target_peer_id)
        await _handle_incoming_ice_candidates(
            signaling_stream, peer_connection, timeout
        )

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

        # Verify connection is established
        # CRITICAL: We need BOTH connectionState AND ICE to be ready for SCTP to work
        connection_established = trio.Event()
        ice_connected = trio.Event()

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

        # CRITICAL: Give SCTP time to initialize after connection is established
        # SCTP needs a moment to set up before data channels can open
        logger.debug("Waiting briefly for SCTP to initialize after connection...")
        await trio.sleep(0.5)

        # CRITICAL: Wait for init channel to open before proceeding
        # This ensures SCTP is fully established and ready for new channels
        # The init channel must open for SCTP to be ready for new channels
        logger.debug(
            "Waiting for 'init' channel to open (required for SCTP establishment)..."
        )

        # Check current state first -
        # channel might have opened during conn establishment
        current_init_state = init_channel.readyState
        logger.debug(f"Init channel state after connection: {current_init_state}")

        if current_init_state == "open":
            logger.info("✅ Init channel already open - SCTP is ready")
            init_channel_ready.set()
        else:
            init_state = init_channel.readyState
            logger.debug(f"Init channel state: {init_state}, waiting for it to open...")

            # Wait for init channel to open
            wait_start_time = trio.current_time()
            max_wait_time = 60.0
            check_interval = 0.2  # Check more frequently

            with trio.move_on_after(max_wait_time) as init_open_scope:
                while not init_channel_ready.is_set():
                    current_channel_state = init_channel.readyState
                    if current_channel_state == "open":
                        logger.info("✅ Init channel is open (checked state directly)")
                        init_channel_ready.set()
                        break
                    elif current_channel_state == "closed":
                        logger.error("❌ Init channel closed before opening!")
                        raise WebRTCError(
                            "Init channel closed before opening - SCTP may have failed"
                        )

                    # Check connection state - if connection fails, abort
                    conn_state = peer_connection.connectionState
                    ice_state = peer_connection.iceConnectionState
                    if conn_state == "failed" or ice_state == "failed":
                        logger.error(
                            f"❌ Connection failed while waiting for init channel "
                            f"(conn_state: {conn_state}, ice_state: {ice_state})"
                        )
                        raise WebRTCError(
                            f"Connection failed while waiting for init channel "
                            f"(conn_state: {conn_state}, ice_state: {ice_state})"
                        )

                    # Check SCTP state periodically
                    try:
                        if hasattr(peer_connection, "sctp") and peer_connection.sctp:
                            if hasattr(peer_connection.sctp, "transport"):
                                sctp_state = getattr(
                                    peer_connection.sctp.transport, "state", "N/A"
                                )
                                elapsed = trio.current_time() - wait_start_time
                                if sctp_state == "connected":
                                    if elapsed % 5.0 < check_interval:  # Log every 5s
                                        logger.debug(
                                            f"SCTP connected, awaiting init channel.."
                                            f"(elapsed: {elapsed:.1f}s, "
                                            f"channel_state: {current_channel_state})"
                                        )
                                elif sctp_state == "closed":
                                    logger.error(
                                        f"❌ SCTP closed while awaiting for "
                                        f"init channel to open "
                                        f"(elapsed: {elapsed:.1f}s, "
                                        f"channel_state: {current_channel_state})"
                                    )
                                    raise WebRTCError(
                                        "SCTP closed while awaiting for "
                                        "init channel to open"
                                    )
                    except WebRTCError:
                        raise
                    except Exception as e:
                        logger.debug(f"Error checking SCTP state: {e}")

                    await trio.sleep(check_interval)

                if init_channel_ready.is_set():
                    elapsed = trio.current_time() - wait_start_time
                    logger.info(
                        f"✅ Init channel opened successfully - SCTP is ready "
                        f"(waited {elapsed:.1f}s)"
                    )

            if init_open_scope.cancelled_caught:
                init_state = init_channel.readyState
                conn_state = peer_connection.connectionState
                ice_state = peer_connection.iceConnectionState
                # Check SCTP state one more time
                sctp_state = "N/A"
                try:
                    if hasattr(peer_connection, "sctp") and peer_connection.sctp:
                        if hasattr(peer_connection.sctp, "transport"):
                            sctp_state = getattr(
                                peer_connection.sctp.transport, "state", "N/A"
                            )
                except Exception:
                    pass

                elapsed = trio.current_time() - wait_start_time
                logger.error(
                    f"❌ Init channel did not open within {max_wait_time}s timeout "
                    f"(elapsed: {elapsed:.1f}s, init_state: {init_state}, "
                    f"sctp_state: {sctp_state}, conn_state: {conn_state}, "
                    f"ice_state: {ice_state}). "
                    "SCTP may not be fully established. This is a critical error."
                )
                raise WebRTCError(
                    f"Init channel failed to open - SCTP not ready "
                    f"(init_state: {init_state}, sctp_state: {sctp_state}, "
                    f"conn_state: {conn_state}, ice_state: {ice_state})"
                )

        await trio.sleep(0.1)

        # CRITICAL: Close init channel FIRST, then create new channel
        # close init channel, wait for it to close,
        # then create new channels through muxer (we create single channel here)
        # This ensures channel IDs are properly freed before reuse
        logger.debug(
            "Closing 'init' channel per spec step 8 (before creating new channel)"
        )
        try:
            if init_channel.readyState == "closed":
                logger.debug("Init channel already closed")
                init_channel_closed.set()
            else:
                bridge = TrioSafeWebRTCOperations._get_bridge()
                await bridge.close_data_channel(init_channel)
                # Wait for init channel to close (matching JavaScript behavior)
                logger.debug("Waiting for init channel to close...")
                with trio.move_on_after(10.0) as close_scope:
                    await init_channel_closed.wait()
                if close_scope.cancelled_caught:
                    logger.warning(
                        "Init channel close event not received, proceed anyway"
                    )
                else:
                    logger.info("✅ Init channel closed successfully")
        except Exception as e:
            logger.warning(f"Error closing init channel: {e}")
            # Continue anyway - channel might be closed already

        await trio.sleep(0.2)

        # Now create new data channel for communication
        # Msgs on RTCDataChannels use the msg framing mechanism.
        # We create a new channel with an empty label
        logger.debug("Creating new data channel for communication")
        try:
            # Create incoming message buffer early to prevent message loss
            message_buffer_send, message_buffer_recv = trio.open_memory_channel(1000)

            def _early_message_handler(message: Any) -> None:
                """
                Early handler that buffers all messages immediately to
                prevent loss.
                """
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
                                f"Initiator early handler buffered {len(data)} bytes"
                            )
                        except trio.WouldBlock:
                            logger.warning("Message buffer full, dropping message")
                        except trio.ClosedResourceError:
                            logger.debug("Message buffer closed")
                except Exception as e:
                    logger.debug(f"Error in early message handler: {e}")

            # Create new data channel with empty label (per spec)
            # This will trigger a 'datachannel' event on the answerer side
            logger.info(
                "🚀 Creating new data channel - this should trigger "
                "datachannel event on answerer"
            )
            new_data_channel = peer_connection.createDataChannel("")
            channel_id = getattr(new_data_channel, "id", "N/A")
            channel_state = new_data_channel.readyState
            logger.info(
                f"✅ Created new data channel for communication "
                f"(label='{new_data_channel.label}', id={channel_id}, "
                f"initial state={channel_state})"
            )

            # Attach early handler immediately after creating channel
            new_data_channel.on("message", _early_message_handler)
            logger.debug("Attached early message handler to new data channel")

            # Give time for the datachannel event to propagate to answerer via SCTP
            # The event should fire when SCTP sends the channel creation message
            logger.debug("Waiting for datachannel event to propagate to answerer...")
            await trio.sleep(
                0.5
            )  # Increased from 0.1s to allow SCTP message to be sent

            # Wait for new channel to open
            new_channel_ready = trio.Event()

            def on_new_channel_open() -> None:
                logger.info("New data channel opened")
                new_channel_ready.set()

            new_data_channel.on("open", on_new_channel_open)

            # Check if already open
            if new_data_channel.readyState == "open":
                new_channel_ready.set()
                logger.info("New data channel already open")
            else:
                current_channel_state = new_data_channel.readyState
                logger.debug(
                    f"Waiting for new data channel to open "
                    f"(current state: {current_channel_state})..."
                )
                # Give more time for channel to open (SCTP needs time after
                # init channel close)
                with trio.move_on_after(15.0) as new_open_scope:
                    await new_channel_ready.wait()
                if new_open_scope.cancelled_caught:
                    # Check connection and SCTP state
                    conn_state = peer_connection.connectionState
                    ice_state = peer_connection.iceConnectionState
                    current_sctp_state = "N/A"
                    try:
                        if hasattr(peer_connection, "sctp") and peer_connection.sctp:
                            if hasattr(peer_connection.sctp, "transport"):
                                current_sctp_state = getattr(
                                    peer_connection.sctp.transport, "state", "N/A"
                                )
                    except Exception:
                        pass
                    logger.warning(
                        f"New data channel did not open within timeout "
                        f"(state: {new_data_channel.readyState}, "
                        f"conn_state: {conn_state}, ice_state: {ice_state}, "
                        f"sctp_state: {current_sctp_state})"
                    )
                    # If SCTP is closed, we can't proceed
                    if current_sctp_state == "closed":
                        raise WebRTCError(
                            f"SCTP transport closed while waiting for new "
                            f"data channel to open "
                            f"(conn_state: {conn_state}, "
                            f"ice_state: {ice_state})"
                        )
                    # If connection is still good, proceed anyway -
                    # channel might open later
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
                            f"New data channel failed to open and connection "
                            f"is not stable "
                            f"(conn_state: {conn_state}, "
                            f"ice_state: {ice_state})"
                        )
        except WebRTCError:
            raise
        except Exception as e:
            logger.error(f"Failed to create new data channel: {e}")
            raise WebRTCError(
                f"Failed to create communication data channel: {e}"
            ) from e

        logger.debug("Closing signaling stream per spec step 8")
        try:
            await signaling_stream.close()
        except Exception as e:
            logger.warning(f"Error closing signaling stream: {e}")

        # Create connection wrapper with the new data channel and message buffer
        connection = WebRTCRawConnection(
            peer_id=target_peer_id,
            peer_connection=peer_connection,
            data_channel=new_data_channel,
            is_initiator=True,
            incoming_message_buffer=message_buffer_recv,
        )

        logger.info(
            f"Successfully established WebRTC connection to {target_peer_id} "
            f"(channel state: {new_data_channel.readyState}, "
            f"conn_state: {peer_connection.connectionState})"
        )

        # CRITICAL: Start buffer consumer in async context
        #  right after connection creation
        # This ensures messages flow from
        # early handler → buffer → receive_channel → read()
        if message_buffer_recv is not None:
            logger.info(
                f"Starting buffer consumer in async context for {target_peer_id}..."
            )
            await connection.start_buffer_consumer_async()
            # Wait for consumer to be ready (with timeout)
            with trio.move_on_after(1.0) as timeout_scope:
                await connection._buffer_consumer_ready.wait()

            if timeout_scope.cancelled_caught:
                logger.warning(
                    f"Buffer consumer ready timeout for {target_peer_id} - "
                    "proceeding anyway"
                )
            else:
                logger.info(
                    f"✅ Buffer consumer is ready for {target_peer_id} - "
                    "messages will flow correctly"
                )

        # CRITICAL: Verify connection is stable before registering handshake
        await trio.sleep(0.1)

        if peer_connection.connectionState == "closed":
            raise WebRTCError(
                "Peer connection closed immediately after creating WebRTCRawConnection"
            )

        if new_data_channel.readyState != "open":
            raise WebRTCError(
                f"Data channel closed immediately after creating WebRTCRawConnection "
                f"(state: {new_data_channel.readyState})"
            )

        # CRITICAL: Verify DTLS and SCTP states before returning connection
        # This prevents "ConnectionError: Cannot send encrypted data, not connected"
        # Wait for DTLS to connect (with timeout)
        # DTLS handshake happens after ICE completes, so we need to wait
        dtls_connected = False
        max_dtls_wait = 10.0
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
            # DTLS state might not be accessible yet, wait a bit
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

        # This ensures handshake is only registered
        #  if conn is stable and ready
        # The handshake will be active during security upgrade
        register_handshake(peer_connection)
        logger.debug(
            f"Registered handshake for peer connection {id(peer_connection)} "
            f"(connection stable, DTLS/SCTP ready, ready for security upgrade)"
        )

        return connection

    except Exception as e:
        logger.error(f"Failed to initiate WebRTC connection: {e}")

        # CRITICAL: Unregister handshake if it was registered
        # This prevents "SCTP closing while handshakes exist" warnings
        if peer_connection:
            from ..aiortc_patch import unregister_handshake

            unregister_handshake(peer_connection)
            try:
                await aio_as_trio(peer_connection.close())
            except (RuntimeError, Exception) as cleanup_error:
                # Check if it's a closed loop issue
                error_str = str(cleanup_error).lower()
                if "closed" in error_str or "no running event loop" in error_str:
                    logger.debug("Event loop closed during cleanup (non-critical)")
                else:
                    logger.warning(
                        f"Error cleaning up peer connection: {cleanup_error}"
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
    """Send a signaling message over the stream with varint length prefix."""
    try:
        #: Messages are sent prefixed with the message length in bytes,
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
        # Read varint-prefixed protobuf message
        # Use read_length_prefixed_protobuf which handles the varint decoding
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


async def _handle_incoming_ice_candidates(
    stream: INetStream, peer_connection: RTCPeerConnection, timeout: float
) -> None:
    """
    Handle incoming ICE candidates from the signaling stream.

    NOTE: This function avoids nested cancel scopes to prevent Trio corruption.
    """
    logger.debug("Handling incoming ICE candidates")

    start_time = trio.current_time()

    while True:
        elapsed = trio.current_time() - start_time
        if elapsed >= timeout:
            logger.warning("ICE candidate receive timeout")
            break

        try:
            # Use remaining timeout, but read in chunks to allow connection checks
            remaining_timeout = timeout - elapsed
            if remaining_timeout <= 0:
                break
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
                # Otherwise, continue to next iteration
                continue

            # stream ended or we became connected
            if not message:
                logger.error("Null message received")
                break

            if message.type != Message.ICE_CANDIDATE:
                logger.error("ICE candidate message expected. Exiting...")
                raise WebRTCError("ICE candidate message expected.")

            # Candidate init cannot be null
            if message.data == "":
                logger.debug("candidate received is empty")
                continue

            logger.debug("Received new ICE Candidate")
            try:
                candidate_init = json.loads(message.data)
            except json.JSONDecodeError:
                logger.error("Invalid ICE candidate JSON: %s", message.data)
                break

            # None means ICE gathering is fully complete
            if candidate_init is None:
                logger.debug("Received ICE candidate null → end-of-ice signal")
                try:
                    await aio_as_trio(peer_connection.addIceCandidate(None))
                except Exception as e:
                    logger.warning(f"Failed to add end-of-ICE candidate: {e}")
                return

            # CandidateInit is expected to be a dict
            if isinstance(candidate_init, dict) and "candidate" in candidate_init:
                # Ensure sdpMLineIndex is present
                if "sdpMLineIndex" not in candidate_init:
                    candidate_init["sdpMLineIndex"] = 0

                candidate = candidate_from_aioice(
                    Candidate.from_sdp(candidate_init["candidate"])
                )
                # Set sdpMLineIndex and sdpMid
                mline_index = candidate_init.get("sdpMLineIndex", 0)
                if hasattr(candidate, "sdpMLineIndex"):
                    candidate.sdpMLineIndex = mline_index
                if not hasattr(candidate, "sdpMid") or candidate.sdpMid is None:
                    candidate.sdpMid = str(mline_index)

                try:
                    await aio_as_trio(peer_connection.addIceCandidate(candidate))
                    logger.debug("Added ICE candidate: %r", candidate_init)
                except Exception as e:
                    logger.warning(f"Failed to add ICE candidate: {e}")
                    continue
            else:
                logger.warning(f"Invalid candidate format: {candidate_init}")

        except WebRTCError:
            # Check timeout before raising
            elapsed = trio.current_time() - start_time
            if elapsed >= timeout:
                logger.warning("Timeout during ICE candidate handling")
                break
            raise
        except Exception as e:
            # Check timeout before continuing
            elapsed = trio.current_time() - start_time
            if elapsed >= timeout:
                logger.warning("Timeout during ICE candidate handling")
                break
            logger.warning(f"Error handling ICE candidate: {e}")
            # Continue trying to read
            continue


async def _wait_for_event(event: trio.Event) -> None:
    """Wait for a trio event to be set"""
    await event.wait()
