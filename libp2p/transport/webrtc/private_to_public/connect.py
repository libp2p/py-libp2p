import logging
from typing import TYPE_CHECKING

from aiortc import RTCDataChannel, RTCSessionDescription
from multiaddr import Multiaddr
import trio
from trio_asyncio import aio_as_trio

from libp2p.peer.id import ID
from libp2p.transport.webrtc.private_to_public.util import (
    SDP,
    fingerprint_to_multiaddr,
    generate_noise_prologue,
    multiaddr_to_fingerprint,
)

from ..connection import WebRTCRawConnection
from .direct_rtc_connection import DirectPeerConnection
from .stream import WebRTCStream

if TYPE_CHECKING:
    from libp2p.abc import IRawConnection

logger = logging.getLogger("libp2p.transport.webrtc.private_to_public")


# pyright: ignore[reportMissingReturnStatement]
async def connect(
    peer_connection: DirectPeerConnection,
    ufrag: str,
    role: str,
    remote_addr: Multiaddr | None = None,
    remote_peer_id: ID | None = None,
) -> "IRawConnection | None":
    """
    Establish a WebRTC-Direct connection, perform the noise handshake,
    and return the upgraded connection.
    """
    # Create data channel for noise handshake (negotiated, id=0)
    handshake_channel: RTCDataChannel = (
        peer_connection.peer_connection.createDataChannel("", negotiated=True, id=0)
    )

    try:
        if role == "client":
            logger.debug("client creating local offer")
            offer = await peer_connection.createOffer()
            logger.debug("client created local offer %s", offer.sdp)
            munged_offer = SDP.munge_offer(offer.sdp, ufrag)
            logger.debug("client setting local offer %s", munged_offer)
            munged_desc = RTCSessionDescription(sdp=munged_offer, type=offer.type)
            await aio_as_trio(peer_connection.setLocalDescription(munged_desc))

            if remote_addr is None:
                raise Exception("Remote address is required for client role")

            answer_sdp = SDP.server_answer_from_multiaddr(remote_addr, ufrag)
            logger.debug("client setting server description %s", answer_sdp["sdp"])
            answer_desc = RTCSessionDescription(
                sdp=answer_sdp["sdp"], type=answer_sdp["type"]
            )
            await aio_as_trio(peer_connection.setRemoteDescription(answer_desc))
        else:
            if remote_addr is None:
                raise Exception("Remote address is required for server role")

            offer_sdp = SDP.client_offer_from_multiaddr(remote_addr, ufrag)
            logger.debug(
                "server setting client %s %s", offer_sdp["type"], offer_sdp["sdp"]
            )
            offer_desc = RTCSessionDescription(
                sdp=offer_sdp["sdp"], type=offer_sdp["type"]
            )
            await aio_as_trio(peer_connection.setRemoteDescription(offer_desc))

            logger.debug("server creating local answer")
            answer = await peer_connection.createAnswer()
            logger.debug("server created local answer")
            munged_answer = SDP.munge_offer(answer.sdp, ufrag)
            logger.debug("server setting local description %s", munged_answer)
            munged_answer_desc = RTCSessionDescription(
                sdp=munged_answer, type=answer.type
            )
            await aio_as_trio(peer_connection.setLocalDescription(munged_answer_desc))

        # TODO: Check if this is the best way
        # Wait for handshake channel to open
        if handshake_channel.readyState != "open":
            logger.debug(
                "%s wait for handshake channel to open, starting status %s",
                role,
                handshake_channel.readyState,
            )
            # Wait for the 'open' event or signal cancellation
            open_event = trio.Event()

            def on_open() -> None:
                open_event.set()

            handshake_channel.on("open", on_open)
            with trio.move_on_after(30):  # 30s timeout
                await open_event.wait()
            if handshake_channel.readyState != "open":
                raise Exception("Handshake data channel did not open in time")

        logger.debug("%s handshake channel opened", role)

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
        local_desc = rtc_pc.localDescription
        local_fingerprint = SDP.get_fingerprint_from_sdp(
            local_desc.sdp if local_desc is not None else None
        )
        if local_fingerprint is None:
            raise Exception("Could not get fingerprint from local description sdp")

        # Setup stream for read and write on RTCDataChannel
        webrtc_stream = WebRTCStream.createStream(  # noqa: F841
            handshake_channel,
            direction="outbound",
        )

        logger.debug("%s performing noise handshake", role)
        # TODO: Complete the noise handshake and connection authentication
        # including securing and upgrading the connection
        # Ref: js-libp2p transport-webrtc connect.ts (see lines 135-199)
        # https://github.com/libp2p/js-libp2p/blob/main/packages/transport-webrtc/src/private-to-public/utils/connect.ts
        if remote_addr is not None:
            noisePrologue = generate_noise_prologue(  # noqa: F841
                local_fingerprint, remote_addr, role
            )
        else:
            noisePrologue = None  # noqa: F841

        if remote_peer_id is None and remote_addr is not None:
            try:
                peer_id_str = remote_addr.value_for_protocol("p2p")
                if peer_id_str:
                    remote_peer_id = ID.from_base58(peer_id_str)
            except Exception:
                remote_peer_id = None

        if remote_peer_id is None:
            raise Exception("Remote peer ID could not be determined for WebRTC-Direct")

        raw_connection = WebRTCRawConnection(
            remote_peer_id,
            rtc_pc,
            handshake_channel,
            is_initiator=(role == "client"),
        )

        setattr(raw_connection, "remote_multiaddr", remote_addr)
        setattr(raw_connection, "remote_fingerprint", remote_fingerprint)
        setattr(raw_connection, "local_fingerprint", local_fingerprint)

        return raw_connection

    except Exception as e:
        logger.error("%s noise handshake failed: %s", role, e)
        raise
