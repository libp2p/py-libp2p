import logging
import json
from typing import Any, Dict, Optional

import trio
from trio_asyncio import aio_as_trio

from libp2p.abc import INetStream, IRawConnection
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from aiortc import (
    RTCConfiguration,
    RTCPeerConnection,
    RTCSessionDescription,
    RTCIceCandidate,
    RTCDataChannel
)

from ..constants import WebRTCError
from ..connection import WebRTCRawConnection

logger = logging.getLogger("webrtc.private.signaling_stream_handler")


async def handle_incoming_stream(
    stream: INetStream,
    rtc_config: RTCConfiguration,
    connection_info: Optional[dict[str, Any]],
    host: Any,
    timeout: float = 30.0
) -> Optional[IRawConnection]:
    """
    Handle incoming signaling stream for WebRTC connection establishment using ED25519 peer IDs.
    
    This function acts as the "answerer" in the WebRTC handshake:
    1. Receives SDP offer from remote peer over signaling stream
    2. Creates SDP answer with ICE candidates
    3. Sends answer back to remote peer
    4. Waits for data channel to be established
    5. Returns WebRTC connection with ED25519 peer ID
    """
    logger.info(f"Handling incoming signaling stream for WebRTC connection")
    
    peer_connection = None
    received_data_channel = None
    
    try:
        # Create peer connection
        peer_connection = RTCPeerConnection(rtc_config)
        
        # Create events for coordination
        data_channel_ready = trio.Event()
        connection_failed = trio.Event()
        
        def on_data_channel(channel: RTCDataChannel) -> None:
            """Handle incoming data channel"""
            nonlocal received_data_channel
            received_data_channel = channel
            logger.info(f"Received data channel: {channel.label}")
            
            def on_channel_open() -> None:
                logger.info("Data channel opened")
                data_channel_ready.set()
            
            channel.on("open", on_channel_open)
        
        # Register data channel handler
        peer_connection.on("datachannel", on_data_channel)
        
        # Read offer from signaling stream
        try:
            offer_data = await stream.read()
            if not offer_data:
                raise WebRTCError("No offer data received")
            
            offer_message = json.loads(offer_data.decode('utf-8'))
            if offer_message.get("type") != "offer":
                raise WebRTCError(f"Expected offer, got: {offer_message.get('type')}")
            
            offer = RTCSessionDescription(
                sdp=offer_message["sdp"],
                type=offer_message["type"]
            )
            
            logger.info("Received SDP offer")
            
        except Exception as e:
            raise WebRTCError(f"Failed to receive or parse offer: {e}")
        
        # Set remote description
        await aio_as_trio(peer_connection.setRemoteDescription)(offer)
        logger.info("Set remote description from offer")
        
        # Create and set local description (answer)
        answer = await aio_as_trio(peer_connection.createAnswer)()
        await aio_as_trio(peer_connection.setLocalDescription)(answer)
        logger.info("Created and set local description (answer)")
        
        # Send answer back
        try:
            answer_message = {
                "type": answer.type,
                "sdp": answer.sdp
            }
            answer_data = json.dumps(answer_message).encode('utf-8')
            await stream.write(answer_data)
            logger.info("Sent SDP answer")
            
        except Exception as e:
            raise WebRTCError(f"Failed to send answer: {e}")
        
        # Helper function to wait for events
        async def _wait_for_event(event: trio.Event) -> None:
            await event.wait()
        
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
        
        if not received_data_channel:
            raise WebRTCError("No data channel received")
        
        # Extract peer ID from connection info or stream
        if connection_info and 'peer_id' in connection_info:
            remote_peer_id = connection_info['peer_id']
        elif hasattr(stream, 'muxed_conn') and hasattr(stream.muxed_conn, 'peer_id'):
            remote_peer_id = stream.muxed_conn.peer_id
        else:
            # Fallback - generate ED25519 peer ID for testing/compatibility
            logger.warning("Could not extract remote peer ID, generating ED25519 fallback")
            # Generate ED25519 key pair
            key_pair = create_new_key_pair()
            remote_peer_id = ID.from_pubkey(key_pair.public_key)
        
        # Create WebRTC connection wrapper with ED25519 peer ID
        webrtc_connection = WebRTCRawConnection(
            remote_peer_id, 
            peer_connection, 
            received_data_channel,
            is_initiator=False  # This is the answerer
        )
        
        logger.info(f"WebRTC connection established with ED25519 peer: {remote_peer_id}")
        return webrtc_connection
        
    except Exception as e:
        logger.error(f"Failed to handle incoming signaling stream: {e}")
        
        # Cleanup on error
        if peer_connection:
            try:
                await aio_as_trio(peer_connection.close)()
            except Exception as cleanup_error:
                logger.warning(f"Error during cleanup: {cleanup_error}")
        
        return None
