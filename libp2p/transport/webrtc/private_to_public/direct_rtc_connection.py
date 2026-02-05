from dataclasses import dataclass
import logging

from aiortc import (
    RTCCertificate,
    RTCConfiguration,
    RTCDtlsFingerprint,
    RTCPeerConnection,
    RTCSessionDescription,
)
from trio_asyncio import aio_as_trio

from .gen_certificate import WebRTCCertificate
from .util import SDP

logger = logging.getLogger("libp2p.transport.webrtc.private_to_public")


@dataclass
class DirectRTCConfiguration:
    ufrag: str
    ice_pwd: str
    rtc_config: RTCConfiguration
    certificate: WebRTCCertificate


class DirectPeerConnection(RTCPeerConnection):
    def __init__(self, direct_config: DirectRTCConfiguration):
        self.ufrag = direct_config.ufrag
        self.ice_pwd = direct_config.ice_pwd
        self._certificate = direct_config.certificate
        super().__init__(direct_config.rtc_config)
        if self._certificate.cert is None or self._certificate.private_key is None:
            raise ValueError("WebRTCCertificate is missing cert or private key")
        aiortc_cert = RTCCertificate(
            key=self._certificate.private_key,
            cert=self._certificate.cert,
        )
        setattr(
            self,
            "_RTCPeerConnection__certificates",
            [aiortc_cert],
        )
        fp_values = [
            f"{fp.algorithm} {fp.value}" for fp in aiortc_cert.getFingerprints()
        ]
        logger.warning(
            "Config certificate, expected fingerprint=%s, aiortc fingerprints=%s",
            self._certificate.fingerprint,
            fp_values,
        )
        self.peer_connection = self
        self._ice_credentials_applied = False

    def _ensure_custom_ice_credentials(self) -> None:
        if self.sctp is None or self.sctp.transport is None:
            return
        try:
            ice_transport = self.sctp.transport.transport
            ice_gatherer = getattr(ice_transport, "iceGatherer", None)
            if ice_gatherer is None:
                return
            connection = getattr(ice_gatherer, "_connection", None)
            if connection is None:
                return
            connection._local_username = self.ufrag  # type: ignore[attr-defined]
            connection._local_password = self.ice_pwd  # type: ignore[attr-defined]
            self._ice_credentials_applied = True
        except (AttributeError, TypeError):
            return

    async def createOffer(self) -> RTCSessionDescription:
        """
        Create SDP offer, patching ICE ufrag and pwd to self.ufrag and self.ice_pwd,
        set as local description, and return the patched RTCSessionDescription.
        The underlying aioice connection is patched after setLocalDescription so
        STUN connectivity checks use the same credentials as the SDP.
        """
        self._ice_credentials_applied = False
        self._ensure_custom_ice_credentials()
        offer = await aio_as_trio(super().createOffer())

        sdp_lines = offer.sdp.splitlines()
        new_lines = []
        for line in sdp_lines:
            if line.startswith("a=ice-ufrag:"):
                new_lines.append(f"a=ice-ufrag:{getattr(self, 'ufrag', self.ufrag)}")
            elif line.startswith("a=ice-pwd:"):
                new_lines.append(f"a=ice-pwd:{getattr(self, 'ice_pwd', self.ice_pwd)}")
            else:
                new_lines.append(line)
        patched_sdp = "\r\n".join(new_lines) + "\r\n"

        patched_offer = RTCSessionDescription(sdp=patched_sdp, type=offer.type)
        self._ice_credentials_applied = False
        self._ensure_custom_ice_credentials()
        await aio_as_trio(self.setLocalDescription(patched_offer))
        return patched_offer

    async def createAnswer(self) -> RTCSessionDescription:
        """
        Create SDP answer, patching ICE ufrag and pwd to self.ufrag and self.ice_pwd,
        set as local description, and return the patched RTCSessionDescription.
        The underlying aioice connection is patched after setLocalDescription so
        STUN connectivity checks use the same credentials as the SDP.
        """
        self._ice_credentials_applied = False
        self._ensure_custom_ice_credentials()
        answer = await aio_as_trio(super().createAnswer())

        sdp_lines = answer.sdp.splitlines()
        new_lines = []
        for line in sdp_lines:
            if line.startswith("a=ice-ufrag:"):
                new_lines.append(f"a=ice-ufrag:{getattr(self, 'ufrag', self.ufrag)}")
            elif line.startswith("a=ice-pwd:"):
                new_lines.append(f"a=ice-pwd:{getattr(self, 'ice_pwd', self.ice_pwd)}")
            else:
                new_lines.append(line)
        patched_sdp = "\r\n".join(new_lines) + "\r\n"

        patched_answer = RTCSessionDescription(sdp=patched_sdp, type=answer.type)
        self._ice_credentials_applied = False
        self._ensure_custom_ice_credentials()
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
        ice_pwd: str,
        rtc_configuration: RTCConfiguration,
        certificate: WebRTCCertificate | None = None,
    ) -> "DirectPeerConnection":
        """
        Create a DirectRTCPeerConnection for dialing,
        similar to the JS createDialerRTCPeerConnection.
        """
        if certificate is None:
            certificate = WebRTCCertificate()
        return DirectPeerConnection(
            DirectRTCConfiguration(
                ufrag=ufrag,
                ice_pwd=ice_pwd,
                rtc_config=rtc_configuration,
                certificate=certificate,
            )
        )
