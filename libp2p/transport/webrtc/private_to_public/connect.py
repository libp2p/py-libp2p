import trio
from aiortc import RTCDataChannel, RTCSessionDescription
from .direct_rtc_connection import DirectPeerConnection
from libp2p.transport.webrtc.private_to_public.util import (
    SDP,
    generate_noise_prologue,
    fingerprint_to_multiaddr,
)
from trio_asyncio import aio_as_trio
from libp2p.transport.webrtc.noise_handshake import (
    generate_noise_prologue,
    NoiseEncrypter,
)
from libp2p.transport.webrtc.connection import WebRTCMultiaddrConnection
from libp2p.transport.webrtc.muxer import DataChannelMuxerFactory
from libp2p.transport.webrtc.constants import WEBRTC_CONNECTION_STATES
import logging

logger = logging.getLogger("libp2p.transport.webrtc.private_to_public")

async def connect(
    peer_connection: DirectPeerConnection,
    ufrag: str,
    role: str
):
    """
    Establish a WebRTC-Direct connection, perform the noise handshake, and return the upgraded connection.
    """
    
    # Create data channel for noise handshake (negotiated, id=0)
    handshake_channel: RTCDataChannel = peer_connection.peer_connection.createDataChannel(
        "", negotiated=True, id=0
    )

    try:
        if role == "client":
            logger.debug("client creating local offer")
            offer = await peer_connection.createOffer()
            logger.debug("client created local offer %s", offer.sdp)
            munged_offer = SDP.munge_offer(offer, ufrag)
            logger.debug("client setting local offer %s", munged_offer.sdp)
            await aio_as_trio(peer_connection.setLocalDescription(munged_offer))

            answer_sdp = SDP.server_answer_from_multiaddr(remote_addr, ufrag)
            logger.debug("client setting server description %s", answer_sdp.sdp)
            await aio_as_trio(peer_connection.setRemoteDescription(answer_sdp))
        else:
            offer_sdp = SDP.client_offer_from_multiaddr(remote_addr, ufrag)
            logger.debug("server setting client %s %s", offer_sdp.type, offer_sdp.sdp)
            await aio_as_trio(peer_connection.setRemoteDescription(offer_sdp))

            logger.debug("server creating local answer")
            answer = await peer_connection.createAnswer()
            logger.debug("server created local answer")
            munged_answer = SDP.munge_offer(answer, ufrag)
            logger.debug("server setting local description %s", munged_answer.sdp)
            await aio_as_trio(peer_connection.setLocalDescription(munged_answer))

    # TODO: Fix this
        # Wait for handshake channel to open
        if handshake_channel.readyState != "open":
            logger.debug(
                "%s wait for handshake channel to open, starting status %s",
                role,
                handshake_channel.readyState,
            )
            # Wait for the 'open' event or signal cancellation
            open_event = trio.Event()

            def on_open():
                open_event.set()

            handshake_channel.on("open", on_open)
            with trio.move_on_after(30):  # 30s timeout
                await open_event.wait()
            if handshake_channel.readyState != "open":
                raise Exception("Handshake data channel did not open in time")

        logger.debug("%s handshake channel opened", role)

        if role == "server":
            remote_fingerprint = peer_connection.remoteFingerprint().value
            remote_addr = fingerprint_to_multiaddr(remote_fingerprint)

        # Get local fingerprint
        local_desc = peer_connection.localDescription
        local_fingerprint = SDP.get_fingerprint_from_sdp(local_desc.sdp)
        if local_fingerprint is None:
            raise Exception("Could not get fingerprint from local description sdp")

        logger.debug("%s performing noise handshake", role)
        #TODO: Complete the noise handshake and connection authentication
        noiseProlouge = generate_noise_prologue(local_fingerprint, remote_addr, role)
        
    except Exception as e:
        logger.error("%s noise handshake failed: %s", role, e)
        raise