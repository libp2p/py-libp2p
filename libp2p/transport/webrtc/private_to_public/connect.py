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


# pyright: ignore[reportMissingReturnStatement]
async def connect(
    peer_connection: DirectPeerConnection,
    ufrag: str,
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
    # Create data channel for noise handshake (negotiated, id=0)
    rtc_pc = peer_connection.peer_connection
    bridge = get_webrtc_bridge()
    cleanup_handlers: list[
        tuple[str, Callable[[dict[str, Any], str], Awaitable[None]]]
    ] = []

    handshake_channel: RTCDataChannel = rtc_pc.createDataChannel(
        "", negotiated=True, id=0
    )

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

        rtc_pc.on("icecandidate", _queue_local_candidate)

        async def _handle_remote_ice(
            message: dict[str, Any], sender_peer_id: str
        ) -> None:
            if sender_peer_id != remote_peer_str:
                return
            msg_ufrag = message.get("ufrag")
            if msg_ufrag is not None and msg_ufrag != ufrag:
                return
            candidate_payload = message.get("candidate")
            async with bridge:
                if candidate_payload is None:
                    await bridge.add_ice_candidate(rtc_pc, None)
                    return
                candidate_obj = candidate_from_aioice(
                    Candidate.from_sdp(candidate_payload.get("candidate", ""))
                )
                candidate_obj.sdpMid = candidate_payload.get("sdpMid")
                candidate_obj.sdpMLineIndex = candidate_payload.get("sdpMLineIndex")
                await bridge.add_ice_candidate(rtc_pc, candidate_obj)

        signal_service.add_handler("ice", _handle_remote_ice)
        cleanup_handlers.append(("ice", _handle_remote_ice))

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

            if certhash is None:
                try:
                    certhash = extract_certhash(remote_addr)
                except Exception:
                    certhash = None

            if offer_handler is not None:
                answer_desc = await offer_handler(munged_desc, ufrag)
            elif signal_service is not None and remote_peer_id is not None:
                answer_desc = await signal_service.negotiate_connection(
                    remote_peer_id,
                    munged_desc,
                    certhash or "",
                    extra={"ufrag": ufrag},
                )
            else:
                raise Exception(
                    "Signal service or offer_handler required for WebRTC-Direct dialing"
                )
            await aio_as_trio(peer_connection.setRemoteDescription(answer_desc))
        else:
            if incoming_offer is not None:
                offer_desc = incoming_offer
            else:
                raise Exception(
                    "Server role requires incoming SDP offer via signaling service"
                )
            await aio_as_trio(peer_connection.setRemoteDescription(offer_desc))

            logger.debug("server creating local answer")
            answer_desc = await peer_connection.createAnswer()
            logger.debug("server created local answer")
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

        if expected_certhash is not None and actual_certhash is not None:
            if expected_certhash != actual_certhash:
                raise Exception(
                    "Remote certhash mismatch detected during WebRTC connection setup"
                )

        if remote_addr is not None and actual_certhash is not None:
            remote_addr = canonicalize_certhash(remote_addr, actual_certhash)

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

        raw_connection.remote_multiaddr = remote_addr
        raw_connection.remote_fingerprint = remote_fingerprint
        raw_connection.local_fingerprint = local_fingerprint
        secure_conn: "IRawConnection | ISecureConn" = raw_connection

        noise_prologue: bytes | None = None
        if remote_addr is not None:
            noise_prologue = generate_noise_prologue(
                local_fingerprint, remote_addr, role
            )

        if security_multistream is not None:
            transport = await security_multistream.select_transport(
                raw_connection, role == "client"
            )
            if hasattr(transport, "set_prologue"):
                transport.set_prologue(noise_prologue)

            if role == "client":
                secure_conn = await transport.secure_outbound(
                    raw_connection, remote_peer_id
                )
            else:
                secure_conn = await transport.secure_inbound(raw_connection)

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
        logger.error("%s noise handshake failed: %s", role, e)
        raise
    finally:
        if signal_service is not None and cleanup_handlers:
            for msg_type, handler in cleanup_handlers:
                signal_service.remove_handler(msg_type, handler)
        if signal_service is not None and remote_peer_id is not None:
            signal_service.pending_local_ice.pop(str(remote_peer_id), None)
