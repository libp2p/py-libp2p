from dataclasses import dataclass

from aiortc import (
    RTCConfiguration,
    RTCDtlsFingerprint,
    RTCPeerConnection,
    RTCSessionDescription,
)
from trio_asyncio import aio_as_trio

from .gen_certificate import WebRTCCertificate
from .util import SDP


@dataclass
class DirectRTCConfiguration:
    ufrag: str
    peer_connection: RTCPeerConnection
    rtc_config: RTCConfiguration


class DirectPeerConnection(RTCPeerConnection):
    def __init__(self, direct_config: DirectRTCConfiguration):
        self.ufrag = direct_config.ufrag
        self.peer_connection = direct_config.peer_connection
        super().__init__(direct_config.rtc_config)

    async def createOffer(self) -> RTCSessionDescription:
        """
        Create SDP offer, patching ICE ufrag and pwd to self.ufrag and self.upwd,
        set as local description, and return the patched RTCSessionDescription.
        """
        offer = await aio_as_trio(super().createOffer())

        sdp_lines = offer.sdp.splitlines()
        new_lines = []
        for line in sdp_lines:
            if line.startswith("a=ice-ufrag:"):
                new_lines.append(f"a=ice-ufrag:{getattr(self, 'ufrag', self.ufrag)}")
            elif line.startswith("a=ice-pwd:"):
                new_lines.append(f"a=ice-pwd:{getattr(self, 'ufrag', self.ufrag)}")
            else:
                new_lines.append(line)
        patched_sdp = "\r\n".join(new_lines) + "\r\n"

        patched_offer = RTCSessionDescription(sdp=patched_sdp, type=offer.type)
        await aio_as_trio(self.setLocalDescription(patched_offer))
        return patched_offer

    async def createAnswer(self) -> RTCSessionDescription:
        """
        Create SDP answer, patching ICE ufrag and pwd to self.ufrag and self.upwd,
        set as local description, and return the patched RTCSessionDescription.
        """
        answer = await aio_as_trio(super().createAnswer())

        sdp_lines = answer.sdp.splitlines()
        new_lines = []
        for line in sdp_lines:
            if line.startswith("a=ice-ufrag:"):
                new_lines.append(f"a=ice-ufrag:{getattr(self, 'ufrag', self.ufrag)}")
            elif line.startswith("a=ice-pwd:"):
                new_lines.append(f"a=ice-pwd:{getattr(self, 'ufrag', self.ufrag)}")
            else:
                new_lines.append(line)
        patched_sdp = "\r\n".join(new_lines) + "\r\n"

        patched_answer = RTCSessionDescription(sdp=patched_sdp, type=answer.type)
        await aio_as_trio(self.setLocalDescription(patched_answer))
        return patched_answer

    def remoteFingerprint(self) -> RTCDtlsFingerprint:
        desc = getattr(self.peer_connection, "remoteDescription", None)
        if desc is not None and desc.sdp:
            fingerprint = SDP.get_fingerprint_from_sdp(desc.sdp)
            if fingerprint:
                parts = fingerprint.split(" ", 1)
                if len(parts) == 2:
                    algorithm, value = parts
                    return RTCDtlsFingerprint(algorithm, value)
                return RTCDtlsFingerprint("sha-256", parts[0])
        return RTCDtlsFingerprint("", "")

    @staticmethod
    async def create_dialer_rtc_peer_connection(
        role: str,
        ufrag: str,
        rtc_configuration: RTCConfiguration,
        certificate: WebRTCCertificate | None = None,
    ) -> "DirectPeerConnection":
        """
        Create a DirectRTCPeerConnection for dialing,
        similar to the JS createDialerRTCPeerConnection.
        """
        if certificate is None:
            certificate = WebRTCCertificate()

        # TODO: ICE servers. Should we use the ones from the rtc_configuration?

        # # ICE servers
        # ice_servers = rtc_config.get("iceServers") if isinstance(rtc_config, dict)
        #               else getattr(rtc_config, "iceServers", None)
        # if ice_servers is None and default_ice_servers is not None:
        #     ice_servers = default_ice_servers

        # if map_ice_servers is not None:
        #     mapped_ice_servers = map_ice_servers(ice_servers)
        # else:
        #     mapped_ice_servers = ice_servers
        # timestamp = datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000
        peer_connection = RTCPeerConnection(
            RTCConfiguration(
                # f"{role}-{timestamp}",
                # disable_fingerprint_verification=True,
                # disable_auto_negotiation=True,
                # certificate_pem_file=certificate.to_pem()[0],
                # key_pem_file=certificate.to_pem()[1],
                # enable_ice_udp_mux=(role == "server"),
                # max_message_size=MAX_MESSAGE_SIZE,
                # ice_servers=mapped_ice_servers,
            )
        )
        return DirectPeerConnection(
            DirectRTCConfiguration(ufrag, peer_connection, rtc_configuration)
        )
