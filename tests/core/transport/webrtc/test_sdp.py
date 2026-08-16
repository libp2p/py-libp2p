"""
Tests for SDP construction and parsing.
"""
# pyrefly: ignore

from __future__ import annotations

import pytest

from libp2p.transport.webrtc.certificate import WebRTCCertificate
from libp2p.transport.webrtc.exceptions import WebRTCConnectionError
from libp2p.transport.webrtc.sdp import SDPBuilder, fingerprint_from_sdp


class TestSDPBuilder:
    def setup_method(self):
        self.cert = WebRTCCertificate.generate()
        self.builder = SDPBuilder(certificate=self.cert)

    def test_build_offer_returns_sdp_and_credentials(self):
        sdp, ufrag, pwd = self.builder.build_offer(host="127.0.0.1", port=9090)
        assert isinstance(sdp, str)
        assert len(ufrag) > 0
        assert len(pwd) > 0

    def test_offer_contains_required_sdp_lines(self):
        sdp, _, _ = self.builder.build_offer(host="127.0.0.1", port=9090)
        assert "v=0" in sdp
        assert "m=application" in sdp
        assert "a=ice-ufrag:" in sdp
        assert "a=ice-pwd:" in sdp
        assert "a=fingerprint:sha-256" in sdp
        assert "a=setup:actpass" in sdp
        assert "a=sctp-port:5000" in sdp
        assert "webrtc-datachannel" in sdp

    def test_offer_contains_candidate(self):
        sdp, _, _ = self.builder.build_offer(host="192.168.1.1", port=4001)
        assert "a=candidate:" in sdp
        assert "192.168.1.1" in sdp
        assert "4001" in sdp

    def test_offer_ipv4(self):
        sdp, _, _ = self.builder.build_offer(host="10.0.0.1", port=5000)
        assert "IN IP4 10.0.0.1" in sdp

    def test_offer_ipv6(self):
        sdp, _, _ = self.builder.build_offer(host="::1", port=5000)
        assert "IN IP6 ::1" in sdp

    def test_answer_has_setup_active(self):
        sdp, _, _ = self.builder.build_answer(
            host="127.0.0.1",
            port=9090,
            remote_ufrag="abc",
            remote_pwd="xyz",
        )
        assert "a=setup:active" in sdp

    def test_offer_fingerprint_matches_certificate(self):
        sdp, _, _ = self.builder.build_offer(host="127.0.0.1", port=9090)
        assert self.cert.fingerprint_hex in sdp

    def test_unique_credentials_per_call(self):
        _, ufrag1, pwd1 = self.builder.build_offer(host="127.0.0.1", port=9090)
        _, ufrag2, pwd2 = self.builder.build_offer(host="127.0.0.1", port=9090)
        # Credentials should be random each time
        assert ufrag1 != ufrag2 or pwd1 != pwd2


class TestFingerprintFromSDP:
    def test_extract_fingerprint(self):
        cert = WebRTCCertificate.generate()
        builder = SDPBuilder(certificate=cert)
        sdp, _, _ = builder.build_offer(host="127.0.0.1", port=9090)
        extracted = fingerprint_from_sdp(sdp)
        assert extracted == cert.fingerprint

    def test_no_fingerprint_raises(self):
        sdp = "v=0\no=- 123 1 IN IP4 127.0.0.1\ns=-\n"
        with pytest.raises(WebRTCConnectionError, match="No SHA-256 fingerprint"):
            fingerprint_from_sdp(sdp)

    def test_malformed_fingerprint_raises(self):
        sdp = "a=fingerprint:sha-256 not:valid:hex:ZZ\n"
        with pytest.raises(WebRTCConnectionError, match="Malformed"):
            fingerprint_from_sdp(sdp)


class TestSDPFromMultiaddr:
    def test_build_from_multiaddr_components(self):
        cert = WebRTCCertificate.generate()
        certhash = cert.fingerprint_to_multibase()
        sdp = SDPBuilder.build_sdp_from_multiaddr(
            host="1.2.3.4",
            port=4001,
            certhash_multibase=certhash,
        )
        assert "1.2.3.4" in sdp
        assert "4001" in sdp
        assert "a=fingerprint:sha-256" in sdp
        # Fingerprint in the SDP should match the cert
        extracted = fingerprint_from_sdp(sdp)
        assert extracted == cert.fingerprint


class TestDirectUsername:
    def test_v1_and_v2_parse(self):
        from libp2p.transport.webrtc.sdp import parse_direct_username

        assert parse_direct_username("libp2p+webrtc+v1/abcdEFGH:cli1") == (
            1,
            "libp2p+webrtc+v1/abcdEFGH",
            "cli1",
        )
        pwd = "p" * 22
        assert parse_direct_username(f"libp2p+webrtc+v2/{pwd}:cli+/9") == (
            2,
            f"libp2p+webrtc+v2/{pwd}",
            "cli+/9",
        )

    @pytest.mark.parametrize(
        "username",
        [
            "libp2p+webrtc+v1/abcd",  # no ':'
            "abcdEFGH:cli1",  # no version prefix -> MUST reject, never assume v1
            "libp2p+webrtc+v9/abcd:cli1",  # unknown version
            "libp2p+webrtc+v1/ab-cd:cli1",  # '-' is not an ice-char
            "libp2p+webrtc+v1/abcd:cl",  # client ufrag < 4
            "libp2p+webrtc+v1/" + "a" * 250 + ":cli1",  # server ufrag > 256
            "libp2p+webrtc+v1/abcd:",  # empty client ufrag
            "",
        ],
    )
    def test_rejects_malformed(self, username):
        from libp2p.transport.webrtc.exceptions import WebRTCConnectionError
        from libp2p.transport.webrtc.sdp import parse_direct_username

        with pytest.raises(WebRTCConnectionError):
            parse_direct_username(username)

    def test_v1_credential_is_a_valid_ufrag_and_pwd(self):
        from libp2p.transport.webrtc.sdp import (
            WEBRTC_DIRECT_V1_PREFIX,
            is_ice_pwd,
            is_ice_ufrag,
            make_v1_credential,
            parse_direct_username,
        )

        cred = make_v1_credential()
        assert cred.startswith(WEBRTC_DIRECT_V1_PREFIX)
        assert is_ice_ufrag(cred) and is_ice_pwd(cred)
        assert parse_direct_username(f"{cred}:abcd")[1] == cred

    def test_generated_credentials_are_ice_chars_only(self):
        import re

        from libp2p.transport.webrtc.sdp import _generate_ice_credential

        for n in (4, 22, 32):
            for _ in range(20):
                c = _generate_ice_credential(n)
                assert len(c) == n
                assert re.fullmatch(r"[A-Za-z0-9+/]+", c), c


class TestSpecSdp:
    def test_inferred_offer_shape(self):
        from libp2p.transport.webrtc.sdp import build_inferred_offer

        sdp = build_inferred_offer(
            client_ufrag="cli1",
            client_pwd="libp2p+webrtc+v1/abcdefghijklmnop",
            remote_host="203.0.113.5",
            remote_port=54321,
        )
        assert "a=ice-ufrag:cli1\n" in sdp
        assert "a=ice-pwd:libp2p+webrtc+v1/abcdefghijklmnop\n" in sdp
        assert "a=setup:active" in sdp  # forces aiortc into DTLS server role
        assert "c=IN IP4 203.0.113.5" in sdp
        assert "a=candidate:1 1 UDP 2130706431 203.0.113.5 54321 typ host" in sdp
        assert "a=end-of-candidates" in sdp
        assert "a=max-message-size:16384" in sdp
        assert "a=fingerprint:sha-256 " in sdp
        assert "a=ice-lite" not in sdp

    def test_synthetic_answer_shape(self):
        from libp2p.transport.webrtc.certificate import WebRTCCertificate
        from libp2p.transport.webrtc.sdp import (
            build_synthetic_answer,
            fingerprint_from_sdp,
        )

        cert = WebRTCCertificate.generate()
        cred = "libp2p+webrtc+v1/abcdefghijklmnop"
        sdp = build_synthetic_answer(
            host="127.0.0.1",
            port=4001,
            certhash_multibase=cert.fingerprint_to_multibase(),
            ufrag=cred,
            pwd=cred,
        )
        assert sdp.index("a=ice-lite") < sdp.index("m=application")
        assert "a=setup:passive" in sdp
        assert f"a=ice-ufrag:{cred}\n" in sdp and f"a=ice-pwd:{cred}\n" in sdp
        assert "a=candidate:1 1 UDP 2130706431 127.0.0.1 4001 typ host" in sdp
        assert "a=end-of-candidates" in sdp
        assert fingerprint_from_sdp(sdp) == cert.fingerprint
