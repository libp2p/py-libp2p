"""
Tests for SDP construction and parsing.
"""

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
