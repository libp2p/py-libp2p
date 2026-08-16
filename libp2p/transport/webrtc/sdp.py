"""
SDP construction and ICE-username helpers for WebRTC Direct.

WebRTC Direct has no signaling exchange:

- the **dialer** builds the server's answer locally from the multiaddr (IP,
  port, certhash) — :func:`build_synthetic_answer`;
- the **listener** infers the dialer's offer from the first inbound STUN
  BINDING REQUEST (its ``USERNAME`` and source address) —
  :func:`parse_direct_username` + :func:`build_inferred_offer`.

The ICE username fragment doubles as the protocol version switch:
``libp2p+webrtc+v1/…`` (SDP munging) or ``libp2p+webrtc+v2/…`` (no munging,
libp2p/specs#715). Note that aiortc **ignores** ICE credentials in SDP text
passed to ``setLocalDescription`` — the real local credentials live on the
aioice ``Connection`` — so "munging" on our own dialer means setting those
fields, not editing SDP (see ``transport.py``).

Spec: https://github.com/libp2p/specs/blob/master/webrtc/webrtc-direct.md
"""

from __future__ import annotations

import base64
import re
import secrets

from .certificate import WebRTCCertificate, fingerprint_from_multibase
from .exceptions import WebRTCConnectionError

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
a=end-of-candidates
"""

# ---------------------------------------------------------------------------
# ICE username / version helpers (spec: "Connection Establishment")
# ---------------------------------------------------------------------------

#: ufrag prefix for the SDP-munging flow (browsers are removing munging).
WEBRTC_DIRECT_V1_PREFIX = "libp2p+webrtc+v1/"
#: ufrag prefix for the no-munging flow (libp2p/specs#715).
WEBRTC_DIRECT_V2_PREFIX = "libp2p+webrtc+v2/"
_VERSION_PREFIXES = {WEBRTC_DIRECT_V1_PREFIX: 1, WEBRTC_DIRECT_V2_PREFIX: 2}

# RFC 8839 §5.4: ice-char = ALPHA / DIGIT / "+" / "/"; ufrag 4..256, pwd 22..256.
_ICE_CHARS = re.compile(r"^[A-Za-z0-9+/]+$")
ICE_UFRAG_MIN, ICE_UFRAG_MAX = 4, 256
ICE_PWD_MIN, ICE_PWD_MAX = 22, 256

# Placeholder for the inferred offer: the listener cannot know the dialer's
# DTLS fingerprint yet (spec step 6.2), so DTLS fingerprint verification is
# disabled for inbound and Noise authenticates instead. aiortc still requires
# *a* fingerprint line to be present.
_PLACEHOLDER_FINGERPRINT = ":".join(["00"] * 32)


def is_ice_ufrag(value: str) -> bool:
    return ICE_UFRAG_MIN <= len(value) <= ICE_UFRAG_MAX and bool(
        _ICE_CHARS.match(value)
    )


def is_ice_pwd(value: str) -> bool:
    return ICE_PWD_MIN <= len(value) <= ICE_PWD_MAX and bool(_ICE_CHARS.match(value))


def parse_direct_username(username: str) -> tuple[int, str, str]:
    """
    Split and validate the STUN ``USERNAME`` of a WebRTC-Direct first contact.

    The dialer sets ``USERNAME = server_ufrag:client_ufrag`` (RFC 8445 §7.2.2)
    where ``server_ufrag`` carries the version prefix. Both halves must be
    valid ufrags. An unknown or missing prefix is rejected — the spec says
    never to guess a version.

    :returns: ``(version, server_ufrag, client_ufrag)``.
    :raises WebRTCConnectionError: on any malformed / unsupported input.
    """
    server_ufrag, sep, client_ufrag = username.partition(":")
    if not sep:
        raise WebRTCConnectionError("STUN USERNAME is not 'server:client'")
    if not (is_ice_ufrag(server_ufrag) and is_ice_ufrag(client_ufrag)):
        raise WebRTCConnectionError("STUN USERNAME halves are not valid ICE ufrags")
    for prefix, version in _VERSION_PREFIXES.items():
        if server_ufrag.startswith(prefix):
            return version, server_ufrag, client_ufrag
    raise WebRTCConnectionError(
        "unknown WebRTC-Direct version prefix in ufrag (want libp2p+webrtc+v1/ "
        "or libp2p+webrtc+v2/)"
    )


def make_v1_credential(random_len: int = 32) -> str:
    """``libp2p+webrtc+v1/<random>`` — used as both ufrag and pwd in v1."""
    return WEBRTC_DIRECT_V1_PREFIX + _generate_ice_credential(random_len)


def build_inferred_offer(
    *,
    client_ufrag: str,
    client_pwd: str,
    remote_host: str,
    remote_port: int,
    max_message_size: int = 16384,
) -> str:
    """
    The dialer's offer as the listener reconstructs it (spec v1 step 6).

    ``a=setup:active`` (spec allows ``actpass`` or ``active``): with
    ``actpass`` aiortc would answer as DTLS *client*, but the listener must
    be the DTLS server. The fingerprint is a placeholder — see
    :data:`_PLACEHOLDER_FINGERPRINT`.
    """
    ip_version = "IP6" if ":" in remote_host else "IP4"
    return _SDP_TEMPLATE.format(
        session_id=secrets.randbelow(2**62),
        ip_version=ip_version,
        host=remote_host,
        port=remote_port,
        ice_ufrag=client_ufrag,
        ice_pwd=client_pwd,
        fingerprint=_PLACEHOLDER_FINGERPRINT,
        setup_role="active",
        max_message_size=max_message_size,
        priority=2130706431,
    )


def build_synthetic_answer(
    *,
    host: str,
    port: int,
    certhash_multibase: str,
    ufrag: str,
    pwd: str,
    max_message_size: int = 16384,
) -> str:
    """
    The server's answer as the dialer synthesises it (spec v1 step 4).

    ICE-Lite, ``a=setup:passive`` (server = DTLS server), single host
    candidate at the multiaddr's IP:port, fingerprint from the certhash (so
    aiortc pins the server's DTLS certificate for us).
    """
    fingerprint_bytes = fingerprint_from_multibase(certhash_multibase)
    fingerprint_hex = ":".join(f"{b:02X}" for b in fingerprint_bytes)
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
        max_message_size=max_message_size,
        priority=2130706431,
    )
    # a=ice-lite is a session-level attribute: insert before the m= line.
    return sdp.replace("m=application", "a=ice-lite\nm=application", 1)


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
            sdp,
            ufrag,
            pwd,
            self._certificate.fingerprint_hex,
            remote_ufrag=remote_ufrag,
            remote_pwd=remote_pwd,
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
    Apply ICE credentials to the SDP (legacy ``SDPBuilder`` path).

    Kept for the experimental HTTP harness. The spec-path credential seams
    are :func:`build_synthetic_answer` / :func:`build_inferred_offer` (SDP
    text) and the aioice ``Connection`` fields set by the dialer (aiortc
    ignores ICE credentials in SDP passed to ``setLocalDescription``).

    :param sdp: The SDP string with local credentials in template slots.
    :param ufrag: Local ICE username fragment.
    :param pwd: Local ICE password.
    :param fingerprint_hex: Colon-separated cert fingerprint.
    :param remote_ufrag: Remote ICE ufrag (unused).
    :param remote_pwd: Remote ICE pwd (unused).
    :returns: The (unmodified) SDP string.
    """
    # Passthrough: the template already carries a=ice-ufrag / a=ice-pwd /
    # a=fingerprint.
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
            hex_str = line[len("a=fingerprint:sha-256 ") :]
            try:
                fingerprint = bytes(int(b, 16) for b in hex_str.split(":"))
            except (ValueError, TypeError) as e:
                raise WebRTCConnectionError(
                    f"Malformed fingerprint in SDP: {hex_str}"
                ) from e
            # SHA-256 digests are exactly 32 bytes; reject anything else so
            # callers never feed an off-size value into the Noise prologue.
            if len(fingerprint) != 32:
                raise WebRTCConnectionError(
                    f"SHA-256 fingerprint must be 32 bytes, got {len(fingerprint)}"
                )
            return fingerprint
    raise WebRTCConnectionError("No SHA-256 fingerprint found in SDP")


def _generate_ice_credential(length: int) -> str:
    """
    Random ICE credential of exactly *length* ice-chars.

    Standard base64 alphabet (``A-Za-z0-9+/``) — RFC 8839 ice-chars. Not
    ``token_urlsafe``: ``-`` and ``_`` are not ice-chars and aioice rejects
    them.
    """
    raw = base64.b64encode(secrets.token_bytes(length)).decode("ascii")
    return raw.replace("=", "")[:length]
