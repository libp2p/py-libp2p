"""
Tests for WebRTC multiaddr parsing and construction.
"""

import pytest
from multiaddr import Multiaddr

from libp2p.transport.webrtc.certificate import WebRTCCertificate
from libp2p.transport.webrtc.exceptions import WebRTCMultiaddrError
from libp2p.transport.webrtc.multiaddr_utils import (
    build_webrtc_direct_multiaddr,
    is_webrtc_direct_multiaddr,
    is_webrtc_multiaddr,
    parse_webrtc_direct_multiaddr,
)


class TestIsWebrtcDirectMultiaddr:
    """Test WebRTC Direct multiaddr detection."""

    def test_valid_ipv4_webrtc_direct(self):
        maddr = Multiaddr("/ip4/127.0.0.1/udp/9090/webrtc-direct")
        assert is_webrtc_direct_multiaddr(maddr)

    def test_valid_ipv4_with_certhash(self):
        maddr = Multiaddr(
            "/ip4/192.168.1.1/udp/4001/webrtc-direct/certhash/uEiBkEKoo3S"
        )
        assert is_webrtc_direct_multiaddr(maddr)

    def test_valid_ipv6_webrtc_direct(self):
        maddr = Multiaddr("/ip6/::1/udp/9090/webrtc-direct")
        assert is_webrtc_direct_multiaddr(maddr)

    def test_tcp_not_webrtc_direct(self):
        maddr = Multiaddr("/ip4/127.0.0.1/tcp/9090")
        assert not is_webrtc_direct_multiaddr(maddr)

    def test_quic_not_webrtc_direct(self):
        maddr = Multiaddr("/ip4/127.0.0.1/udp/9090/quic-v1")
        assert not is_webrtc_direct_multiaddr(maddr)

    def test_missing_udp_not_valid(self):
        # webrtc-direct without udp is not valid
        maddr = Multiaddr("/ip4/127.0.0.1/tcp/9090/webrtc-direct")
        assert not is_webrtc_direct_multiaddr(maddr)


class TestIsWebrtcMultiaddr:
    """Test relay-based WebRTC multiaddr detection."""

    def test_valid_relay_webrtc(self):
        # Use a valid base58 peer ID (Ed25519 key hash)
        relay_peer_id = "12D3KooWDpJ7As7BWAwRMfu1VU2WCqNjvq387JEYKDBj4kx6nXTN"
        maddr = Multiaddr(
            f"/ip4/1.2.3.4/udp/4001/quic-v1/p2p/{relay_peer_id}/p2p-circuit/webrtc"
        )
        assert is_webrtc_multiaddr(maddr)

    def test_webrtc_direct_is_not_relay_webrtc(self):
        maddr = Multiaddr("/ip4/127.0.0.1/udp/9090/webrtc-direct")
        assert not is_webrtc_multiaddr(maddr)

    def test_plain_tcp_not_webrtc(self):
        maddr = Multiaddr("/ip4/127.0.0.1/tcp/4001")
        assert not is_webrtc_multiaddr(maddr)


class TestBuildWebrtcDirectMultiaddr:
    """Test multiaddr construction."""

    def test_build_ipv4(self):
        cert = WebRTCCertificate.generate()
        certhash = cert.fingerprint_to_multibase()
        maddr = build_webrtc_direct_multiaddr("127.0.0.1", 9090, certhash)
        assert is_webrtc_direct_multiaddr(maddr)
        maddr_str = str(maddr)
        assert "/ip4/127.0.0.1/" in maddr_str
        assert "/udp/9090/" in maddr_str
        assert "/webrtc-direct/" in maddr_str
        assert f"/certhash/{certhash}" in maddr_str

    def test_build_ipv6(self):
        cert = WebRTCCertificate.generate()
        certhash = cert.fingerprint_to_multibase()
        maddr = build_webrtc_direct_multiaddr("::1", 9090, certhash)
        assert is_webrtc_direct_multiaddr(maddr)
        assert "/ip6/" in str(maddr)

    def test_build_with_peer_id(self):
        cert = WebRTCCertificate.generate()
        certhash = cert.fingerprint_to_multibase()
        peer_id = "12D3KooWDpJ7As7BWAwRMfu1VU2WCqNjvq387JEYKDBj4kx6nXTN"
        maddr = build_webrtc_direct_multiaddr(
            "127.0.0.1", 9090, certhash, peer_id=peer_id
        )
        assert f"/p2p/{peer_id}" in str(maddr)


class TestParseWebrtcDirectMultiaddr:
    """Test multiaddr parsing."""

    def test_parse_basic(self):
        cert = WebRTCCertificate.generate()
        certhash = cert.fingerprint_to_multibase()
        maddr = build_webrtc_direct_multiaddr("127.0.0.1", 9090, certhash)
        host, port, parsed_certhash, peer_id = parse_webrtc_direct_multiaddr(maddr)
        assert host == "127.0.0.1"
        assert port == 9090
        assert parsed_certhash == certhash
        assert peer_id is None

    def test_parse_with_peer_id(self):
        cert = WebRTCCertificate.generate()
        certhash = cert.fingerprint_to_multibase()
        expected_peer = "12D3KooWJdGFj8RkDMPSLFsgAbHfcLTwSm3GVnSCbGTAoMnGcEms"
        maddr = build_webrtc_direct_multiaddr(
            "192.168.1.1", 4001, certhash, peer_id=expected_peer
        )
        host, port, parsed_certhash, peer_id = parse_webrtc_direct_multiaddr(maddr)
        assert host == "192.168.1.1"
        assert port == 4001
        assert parsed_certhash == certhash
        assert peer_id == expected_peer

    def test_parse_invalid_multiaddr(self):
        maddr = Multiaddr("/ip4/127.0.0.1/tcp/9090")
        with pytest.raises(WebRTCMultiaddrError, match="Not a valid"):
            parse_webrtc_direct_multiaddr(maddr)

    def test_roundtrip_build_parse(self):
        """Build a multiaddr and parse it back — values should survive."""
        cert = WebRTCCertificate.generate()
        certhash = cert.fingerprint_to_multibase()
        expected_peer = "12D3KooWRBy97UB99e3J6hiPesre1MZeuNQvfan7ATZ8HbRL9vbs"
        original_maddr = build_webrtc_direct_multiaddr(
            "10.0.0.1", 5555, certhash, peer_id=expected_peer
        )
        host, port, parsed_hash, peer_id = parse_webrtc_direct_multiaddr(original_maddr)
        assert host == "10.0.0.1"
        assert port == 5555
        assert parsed_hash == certhash
        assert peer_id == "12D3KooWRBy97UB99e3J6hiPesre1MZeuNQvfan7ATZ8HbRL9vbs"
