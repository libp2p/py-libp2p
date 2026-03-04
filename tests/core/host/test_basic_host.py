from unittest.mock import (
    AsyncMock,
    MagicMock,
)

import pytest
from multiaddr import Multiaddr

from libp2p import (
    new_swarm,
)
from libp2p.crypto.rsa import (
    create_new_key_pair,
)
from libp2p.host.basic_host import (
    BasicHost,
)
from libp2p.host.defaults import (
    get_default_protocols,
)
from libp2p.host.exceptions import (
    StreamFailure,
)


def test_default_protocols():
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    mux = host.get_mux()
    handlers = mux.handlers
    # NOTE: comparing keys for equality as handlers may be closures that do not compare
    # in the way this test is concerned with
    assert handlers.keys() == get_default_protocols(host).keys()


@pytest.mark.trio
async def test_swarm_stream_handler_no_protocol_selected(monkeypatch):
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    # Create a mock net_stream
    net_stream = MagicMock()
    net_stream.reset = AsyncMock()
    net_stream.muxed_conn.peer_id = "peer-test"

    # Monkeypatch negotiate to simulate "no protocol selected"
    async def fake_negotiate(comm, timeout):
        return None, None

    monkeypatch.setattr(host.multiselect, "negotiate", fake_negotiate)

    # Now run the handler and expect StreamFailure
    with pytest.raises(
        StreamFailure, match="Failed to negotiate protocol: no protocol selected"
    ):
        await host._swarm_stream_handler(net_stream)

    # Ensure reset was called since negotiation failed
    net_stream.reset.assert_awaited()


def test_get_addrs_and_transport_addrs():
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    # Mock the network listeners
    mock_transport = MagicMock()
    raw_addr = Multiaddr("/ip4/127.0.0.1/tcp/8000")
    mock_transport.get_addrs.return_value = [raw_addr]

    # Inject into swarm listeners
    # swarm.listeners is a dict
    swarm.listeners = {"tcp": mock_transport}

    # Test get_transport_addrs
    transport_addrs = host.get_transport_addrs()
    assert len(transport_addrs) == 1
    assert transport_addrs[0] == raw_addr
    assert str(transport_addrs[0]) == "/ip4/127.0.0.1/tcp/8000"

    # Test get_addrs
    addrs = host.get_addrs()
    assert len(addrs) == 1
    addr_str = str(addrs[0])
    peer_id_str = str(host.get_id())
    assert peer_id_str in addr_str
    # multiaddr might normalize /p2p/ to /ipfs/
    assert addr_str.endswith(f"/p2p/{peer_id_str}") or addr_str.endswith(
        f"/ipfs/{peer_id_str}"
    )


@pytest.mark.trio
async def test_initiate_autotls_procedure_builds_transport_aware_broker_multiaddr(
    monkeypatch, tmp_path
):
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)
    peer_id = str(host.get_id())

    # Ensure procedure takes the ACME path (no cached cert present).
    monkeypatch.setattr(
        "libp2p.utils.paths.AUTOTLS_CERT_PATH", tmp_path / "missing-autotls-cert.pem"
    )

    captured_addrs = []

    class FakeACMEClient:
        def __init__(self, private_key, peer_id):
            self.private_key = private_key
            self.peer_id = peer_id
            self.key_auth = "fake-key-auth"
            self.b36_peerid = "fake-b36-peer-id"

        async def create_acme_acct(self):
            return None

        async def initiate_order(self):
            return None

        async def get_dns01_challenge(self):
            return None

        async def notify_dns_ready(self):
            return None

        async def fetch_cert_url(self):
            return None

        async def fetch_certificate(self):
            return None

    class FakeBrokerClient:
        def __init__(self, private_key, addr, key_auth, b36_peerid):
            self.private_key = private_key
            self.addr = addr
            self.key_auth = key_auth
            self.b36_peerid = b36_peerid
            captured_addrs.append(addr)

        async def http_peerid_auth(self):
            return None

        async def wait_for_dns(self):
            return None

    monkeypatch.setattr("libp2p.host.basic_host.ACMEClient", FakeACMEClient)
    monkeypatch.setattr("libp2p.host.basic_host.BrokerClient", FakeBrokerClient)

    # QUIC case should advertise /udp/{port}/quic-v1
    monkeypatch.setattr(
        host,
        "get_addrs",
        lambda: [Multiaddr(f"/ip4/127.0.0.1/udp/4001/quic-v1/p2p/{peer_id}")],
    )
    monkeypatch.setattr(
        host,
        "get_transport_addrs",
        lambda: [Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1")],
    )
    await host.initiate_autotls_procedure(public_ip="11.22.33.44")

    quic_addr = captured_addrs[-1]
    assert quic_addr.value_for_protocol("ip4") == "11.22.33.44"
    assert "/udp/4001/quic-v1" in str(quic_addr)

    # TCP case should advertise /tcp/{port}
    monkeypatch.setattr(
        host,
        "get_addrs",
        lambda: [Multiaddr(f"/ip4/127.0.0.1/tcp/4002/p2p/{peer_id}")],
    )
    monkeypatch.setattr(
        host,
        "get_transport_addrs",
        lambda: [Multiaddr("/ip4/127.0.0.1/tcp/4002")],
    )
    await host.initiate_autotls_procedure(public_ip="11.22.33.44")

    tcp_addr = captured_addrs[-1]
    assert tcp_addr.value_for_protocol("ip4") == "11.22.33.44"
    assert "/tcp/4002" in str(tcp_addr)
    assert "/quic-v1" not in str(tcp_addr)


@pytest.mark.trio
async def test_initiate_autotls_procedure_supports_udp_only_public_ip_path(
    monkeypatch, tmp_path
):
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)
    peer_id = str(host.get_id())

    # Ensure procedure takes the ACME path (no cached cert present).
    monkeypatch.setattr(
        "libp2p.utils.paths.AUTOTLS_CERT_PATH", tmp_path / "missing-autotls-cert.pem"
    )

    captured_addrs = []

    class FakeACMEClient:
        def __init__(self, private_key, peer_id):
            self.private_key = private_key
            self.peer_id = peer_id
            self.key_auth = "fake-key-auth"
            self.b36_peerid = "fake-b36-peer-id"

        async def create_acme_acct(self):
            return None

        async def initiate_order(self):
            return None

        async def get_dns01_challenge(self):
            return None

        async def notify_dns_ready(self):
            return None

        async def fetch_cert_url(self):
            return None

        async def fetch_certificate(self):
            return None

    class FakeBrokerClient:
        def __init__(self, private_key, addr, key_auth, b36_peerid):
            self.private_key = private_key
            self.addr = addr
            self.key_auth = key_auth
            self.b36_peerid = b36_peerid
            captured_addrs.append(addr)

        async def http_peerid_auth(self):
            return None

        async def wait_for_dns(self):
            return None

    monkeypatch.setattr("libp2p.host.basic_host.ACMEClient", FakeACMEClient)
    monkeypatch.setattr("libp2p.host.basic_host.BrokerClient", FakeBrokerClient)

    # Only UDP QUIC addresses are available; no TCP address at all.
    monkeypatch.setattr(
        host,
        "get_addrs",
        lambda: [Multiaddr(f"/ip4/11.22.33.44/udp/4001/quic-v1/p2p/{peer_id}")],
    )
    monkeypatch.setattr(
        host,
        "get_transport_addrs",
        lambda: [Multiaddr("/ip4/11.22.33.44/udp/4001/quic-v1")],
    )

    # Should not raise RuntimeError and should register a QUIC broker multiaddr.
    await host.initiate_autotls_procedure(public_ip=None)

    assert captured_addrs
    broker_addr = captured_addrs[-1]
    assert "/ip4/11.22.33.44/udp/4001/quic-v1" in str(broker_addr)
