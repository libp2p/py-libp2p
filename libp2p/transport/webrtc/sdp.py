"""
SDP construction for WebRTC Direct.

For WebRTC Direct, there is no signaling exchange — the client constructs an
SDP offer locally from the server's multiaddr (IP, port, certificate hash).
The server answers with its own locally-constructed SDP.

All ICE credential injection is isolated in :meth:`SDPBuilder._apply_ice_credentials`
so that when Chrome removes ICE credential munging (libp2p/specs#672) only
that single method needs to change.

Spec: https://github.com/libp2p/specs/blob/master/webrtc/webrtc-direct.md
"""

from __future__ import annotations

import hashlib
import logging
import secrets

from .certificate import WebRTCCertificate, fingerprint_from_multibase
from .exceptions import WebRTCConnectionError

logger = logging.getLogger(__name__)

# SDP template for a data-channel-only WebRTC session.
# Based on the minimal SDP that go-libp2p and js-libp2p generate.
_SDP_TEMPLATE = """\
v=0
o=- {session_id} 1 IN {ip_version} {host}
s=-
t=0 0
a=group:BUNDLE 0
a=msid-semantic:WMS
m=application {port} UDP/DTLS/SCTP webrtc-datachannel
c=IN {ip_version} {host}
a=mid:0
a=ice-ufrag:{ice_ufrag}
a=ice-pwd:{ice_pwd}
a=fingerprint:sha-256 {fingerprint}
a=setup:{setup_role}
a=sctp-port:5000
a=max-message-size:{max_message_size}
a=candidate:1 1 UDP {priority} {host} {port} typ host
"""


class SDPBuilder:
    """
    Builds SDP offer/answer for WebRTC Direct connections.

    Usage::

        builder = SDPBuilder(certificate=my_cert)
        offer_sdp = builder.build_offer(host="127.0.0.1", port=9090)
        answer_sdp = builder.build_answer(
            host="127.0.0.1", port=9090, remote_ufrag="...", remote_pwd="..."
        )
    """

    def __init__(
        self,
        certificate: WebRTCCertificate,
        max_message_size: int = 16384,
    ) -> None:
        self._certificate = certificate
        self._max_message_size = max_message_size

    def build_offer(
        self,
        host: str,
        port: int,
    ) -> tuple[str, str, str]:
        """
        Build an SDP offer for initiating a WebRTC Direct connection.

        :param host: Remote server IP address.
        :param port: Remote server UDP port.
        :returns: Tuple of ``(sdp_string, ice_ufrag, ice_pwd)``.
        """
        ufrag = _generate_ice_credential(4)
        pwd = _generate_ice_credential(22)
        sdp = self._build_sdp(
            host=host,
            port=port,
            ice_ufrag=ufrag,
            ice_pwd=pwd,
            setup_role="actpass",
        )
        return sdp, ufrag, pwd

    def build_answer(
        self,
        host: str,
        port: int,
        remote_ufrag: str,
        remote_pwd: str,
    ) -> tuple[str, str, str]:
        """
        Build an SDP answer in response to a remote offer.

        Per RFC 8445 §5.2, the answer includes its own fresh ufrag/pwd for
        connectivity checks.  The remote credentials are passed through to
        ``_apply_ice_credentials`` for the ICE agent to use during
        connectivity checks (needed when specs#672 changes the credential
        injection mechanism).

        :param host: Local listening IP address.
        :param port: Local listening UDP port.
        :param remote_ufrag: ICE ufrag from the remote offer.
        :param remote_pwd: ICE pwd from the remote offer.
        :returns: Tuple of ``(sdp_string, local_ice_ufrag, local_ice_pwd)``.
        """
        ufrag = _generate_ice_credential(4)
        pwd = _generate_ice_credential(22)
        sdp = self._build_sdp(
            host=host,
            port=port,
            ice_ufrag=ufrag,
            ice_pwd=pwd,
            setup_role="active",
        )
        sdp = _apply_ice_credentials(
            sdp, ufrag, pwd, self._certificate.fingerprint_hex,
            remote_ufrag=remote_ufrag, remote_pwd=remote_pwd,
        )
        return sdp, ufrag, pwd

    @staticmethod
    def build_sdp_from_multiaddr(
        host: str,
        port: int,
        certhash_multibase: str,
    ) -> str:
        """
        Build a server-side SDP from multiaddr components for WebRTC Direct.

        For WebRTC Direct the client knows the server's cert hash from the
        multiaddr.  This constructs the SDP that the server would advertise.

        :param host: Server IP address.
        :param port: Server UDP port.
        :param certhash_multibase: Multibase-encoded certificate fingerprint.
        :returns: SDP string.
        """
        fingerprint_bytes = fingerprint_from_multibase(certhash_multibase)
        fingerprint_hex = ":".join(f"{b:02X}" for b in fingerprint_bytes)
        ufrag = _generate_ice_credential(4)
        pwd = _generate_ice_credential(22)

        ip_version = "IP6" if ":" in host else "IP4"
        sdp = _SDP_TEMPLATE.format(
            session_id=secrets.randbelow(2**62),
            ip_version=ip_version,
            host=host,
            port=port,
            ice_ufrag=ufrag,
            ice_pwd=pwd,
            fingerprint=fingerprint_hex,
            setup_role="passive",
            max_message_size=16384,
            priority=2130706431,
        )
        return _apply_ice_credentials(sdp, ufrag, pwd, fingerprint_hex)

    def _build_sdp(
        self,
        host: str,
        port: int,
        ice_ufrag: str,
        ice_pwd: str,
        setup_role: str,
    ) -> str:
        """Build a raw SDP string (credentials already in template)."""
        ip_version = "IP6" if ":" in host else "IP4"
        return _SDP_TEMPLATE.format(
            session_id=secrets.randbelow(2**62),
            ip_version=ip_version,
            host=host,
            port=port,
            ice_ufrag=ice_ufrag,
            ice_pwd=ice_pwd,
            fingerprint=self._certificate.fingerprint_hex,
            setup_role=setup_role,
            max_message_size=self._max_message_size,
            priority=2130706431,
        )

    @property
    def local_fingerprint_bytes(self) -> bytes:
        """Raw SHA-256 fingerprint of the local certificate."""
        return self._certificate.fingerprint

    @property
    def local_fingerprint_hex(self) -> str:
        """Colon-separated hex fingerprint for SDP lines."""
        return self._certificate.fingerprint_hex


def _apply_ice_credentials(
    sdp: str,
    ufrag: str,
    pwd: str,
    fingerprint_hex: str,
    remote_ufrag: str | None = None,
    remote_pwd: str | None = None,
) -> str:
    """
    Apply ICE credentials to the SDP.

    **This is the single seam for libp2p/specs#672.**  When Chrome drops
    ICE credential munging support, only this function needs to change.
    Currently a no-op passthrough — local credentials are already in the
    SDP template.  The remote credentials are accepted but unused until
    the spec changes require injecting them via a separate mechanism.

    :param sdp: The SDP string with local credentials in template slots.
    :param ufrag: Local ICE username fragment.
    :param pwd: Local ICE password.
    :param fingerprint_hex: Colon-separated cert fingerprint.
    :param remote_ufrag: Remote ICE ufrag (for answer SDP / ICE agent).
    :param remote_pwd: Remote ICE pwd (for answer SDP / ICE agent).
    :returns: The (possibly modified) SDP string.
    """
    # Currently a passthrough.  The SDP template already contains
    # a=ice-ufrag, a=ice-pwd, and a=fingerprint lines.  Remote
    # credentials will be used when aiortc's ICE agent is wired up.
    return sdp


def fingerprint_from_sdp(sdp: str) -> bytes:
    """
    Extract the DTLS certificate fingerprint from an SDP string.

    Looks for the ``a=fingerprint:sha-256`` line and parses the
    colon-separated hex digest.

    :param sdp: SDP string.
    :returns: Raw SHA-256 fingerprint bytes (32 bytes).
    :raises WebRTCConnectionError: If no valid fingerprint line found.
    """
    for line in sdp.splitlines():
        line = line.strip()
        if line.startswith("a=fingerprint:sha-256 "):
            hex_str = line[len("a=fingerprint:sha-256 "):]
            try:
                return bytes(int(b, 16) for b in hex_str.split(":"))
            except (ValueError, TypeError) as e:
                raise WebRTCConnectionError(
                    f"Malformed fingerprint in SDP: {hex_str}"
                ) from e
    raise WebRTCConnectionError("No SHA-256 fingerprint found in SDP")


def _generate_ice_credential(length: int) -> str:
    """Generate a random ICE credential string (alphanumeric)."""
    return secrets.token_urlsafe(length)[:length]
