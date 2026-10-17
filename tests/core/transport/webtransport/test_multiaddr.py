"""Unit tests for WebTransport multiaddr helpers."""

from __future__ import annotations

import pytest
from multiaddr import Multiaddr

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.webtransport.certificate import WebTransportCertificate
from libp2p.transport.webtransport.exceptions import WebTransportMultiaddrError
from libp2p.transport.webtransport.multiaddr_utils import (
    build_webtransport_multiaddr,
    extract_certhashes,
    is_webtransport_multiaddr,
    parse_webtransport_multiaddr,
)


def test_is_webtransport_multiaddr():
    assert is_webtransport_multiaddr(
        Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1/webtransport")
    )
    assert not is_webtransport_multiaddr(Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1"))
    assert not is_webtransport_multiaddr(Multiaddr("/ip4/127.0.0.1/tcp/4001"))


def test_build_and_parse_with_dual_certhash():
    c1 = WebTransportCertificate.generate()
    c2 = WebTransportCertificate.generate()
    hashes = [c1.fingerprint_to_multibase(), c2.fingerprint_to_multibase()]
    peer = ID.from_pubkey(create_new_key_pair().public_key).to_base58()
    maddr = build_webtransport_multiaddr("127.0.0.1", 9443, hashes, peer_id=peer)

    assert is_webtransport_multiaddr(maddr)
    host, port, got_hashes, peer_id = parse_webtransport_multiaddr(maddr)
    assert host == "127.0.0.1"
    assert port == 9443
    assert got_hashes == hashes
    assert extract_certhashes(maddr) == hashes
    assert peer_id == peer


def test_build_rejects_bad_certhash_prefix():
    with pytest.raises(WebTransportMultiaddrError):
        build_webtransport_multiaddr("127.0.0.1", 1, ["xNotValid"])


def test_parse_rejects_plain_quic():
    with pytest.raises(WebTransportMultiaddrError):
        parse_webtransport_multiaddr(Multiaddr("/ip4/127.0.0.1/udp/1/quic-v1"))
