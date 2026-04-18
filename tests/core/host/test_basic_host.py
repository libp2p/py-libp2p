from collections.abc import Sequence
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
from libp2p.custom_types import TProtocol
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


def test_remove_stream_handler_removes_protocol():
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    protocol = TProtocol("/test/remove/1.0.0")

    async def dummy_handler(stream):
        pass

    # Register and verify it's present
    host.set_stream_handler(protocol, dummy_handler)
    assert protocol in host.get_mux().handlers

    # Remove and verify it's gone
    host.remove_stream_handler(protocol)
    assert protocol not in host.get_mux().handlers


def test_remove_stream_handler_nonexistent_is_safe():
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    # Removing a protocol that was never registered should not raise
    host.remove_stream_handler(TProtocol("/nonexistent/1.0.0"))


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


def _make_host_with_listener(
    announce_addrs: Sequence[Multiaddr] | None = None,
):
    """Helper: create a BasicHost with a mocked listener returning a known addr."""
    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm, announce_addrs=announce_addrs)
    mock_transport = MagicMock()
    mock_transport.get_addrs.return_value = [Multiaddr("/ip4/127.0.0.1/tcp/8000")]
    swarm.listeners = {"tcp": mock_transport}
    return host


def test_announce_addrs_replaces_listen_addrs():
    announce = [Multiaddr("/ip4/1.2.3.4/tcp/4001")]
    host = _make_host_with_listener(announce_addrs=announce)

    addrs = host.get_addrs()
    peer_id_str = str(host.get_id())

    # Should contain only the announce addr, not the listen addr
    assert len(addrs) == 1
    addr_str = str(addrs[0])
    assert "/ip4/1.2.3.4/tcp/4001" in addr_str
    assert "/ip4/127.0.0.1/tcp/8000" not in addr_str
    assert peer_id_str in addr_str

    # get_transport_addrs still returns the real listen addr
    transport_addrs = host.get_transport_addrs()
    assert str(transport_addrs[0]) == "/ip4/127.0.0.1/tcp/8000"


def test_announce_addrs_strips_wrong_peer_id():
    wrong_peer_id = "QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN"
    announce = [Multiaddr(f"/ip4/1.2.3.4/tcp/4001/p2p/{wrong_peer_id}")]
    host = _make_host_with_listener(announce_addrs=announce)

    addrs = host.get_addrs()
    peer_id_str = str(host.get_id())

    assert len(addrs) == 1
    addr_str = str(addrs[0])
    # Wrong peer id must be stripped and replaced with the host's own
    assert wrong_peer_id not in addr_str
    assert addr_str == f"/ip4/1.2.3.4/tcp/4001/p2p/{peer_id_str}"


def test_announce_addrs_empty_list_advertises_nothing():
    host = _make_host_with_listener(announce_addrs=[])

    addrs = host.get_addrs()
    assert addrs == []


def test_announce_addrs_multiple():
    announce = [
        Multiaddr("/ip4/1.2.3.4/tcp/4001"),
        Multiaddr("/ip4/5.6.7.8/tcp/4002"),
    ]
    host = _make_host_with_listener(announce_addrs=announce)

    addrs = host.get_addrs()
    peer_id_str = str(host.get_id())

    assert len(addrs) == 2
    assert str(addrs[0]) == f"/ip4/1.2.3.4/tcp/4001/p2p/{peer_id_str}"
    assert str(addrs[1]) == f"/ip4/5.6.7.8/tcp/4002/p2p/{peer_id_str}"


def test_announce_addrs_with_correct_peer_id():
    # First create a host to get its peer ID, then set announce with that ID
    host = _make_host_with_listener(announce_addrs=[])
    peer_id_str = str(host.get_id())

    # Set announce addr that already includes the correct /p2p/ suffix
    host._announce_addrs = [Multiaddr(f"/ip4/1.2.3.4/tcp/4001/p2p/{peer_id_str}")]

    addrs = host.get_addrs()

    assert len(addrs) == 1
    # Should still have exactly one /p2p/ component, no duplication
    assert str(addrs[0]) == f"/ip4/1.2.3.4/tcp/4001/p2p/{peer_id_str}"


def test_get_addrs_appends_observed_when_no_announce():
    """Observed addresses are appended to get_addrs when announce_addrs is None."""
    host = _make_host_with_listener(announce_addrs=None)
    observed = Multiaddr("/ip4/5.6.7.8/tcp/4001")
    fake_manager = MagicMock()
    fake_manager.addrs.return_value = [observed]
    host._observed_addr_manager = fake_manager

    addrs = host.get_addrs()
    peer_id_str = str(host.get_id())

    addr_strs = [str(a) for a in addrs]
    assert f"/ip4/127.0.0.1/tcp/8000/p2p/{peer_id_str}" in addr_strs
    assert f"/ip4/5.6.7.8/tcp/4001/p2p/{peer_id_str}" in addr_strs


def test_get_addrs_skips_observed_when_announce_set():
    """
    announce_addrs acts as a static AddrsFactory (like go-libp2p): observed
    addresses are still recorded but not advertised via get_addrs.
    """
    announce = [Multiaddr("/ip4/1.2.3.4/tcp/4001")]
    host = _make_host_with_listener(announce_addrs=announce)
    observed = Multiaddr("/ip4/5.6.7.8/tcp/4001")
    fake_manager = MagicMock()
    fake_manager.addrs.return_value = [observed]
    host._observed_addr_manager = fake_manager

    addrs = host.get_addrs()
    addr_strs = [str(a) for a in addrs]
    assert len(addrs) == 1
    assert "/ip4/1.2.3.4/tcp/4001" in addr_strs[0]
    assert not any("5.6.7.8" in s for s in addr_strs)
    # Observed manager's addrs() must not be consulted at all in this branch.
    fake_manager.addrs.assert_not_called()


def test_get_addrs_deduplicates_observed_matching_transport():
    """If the observed address equals a listen addr it must not be duplicated."""
    host = _make_host_with_listener(announce_addrs=None)
    fake_manager = MagicMock()
    fake_manager.addrs.return_value = [
        Multiaddr("/ip4/127.0.0.1/tcp/8000"),
    ]
    host._observed_addr_manager = fake_manager

    addrs = host.get_addrs()
    assert len(addrs) == 1


def test_get_nat_type_delegates_to_observed_addr_manager():
    """BasicHost.get_nat_type() is a thin pass-through to ObservedAddrManager."""
    from libp2p.host.observed_addr_manager import NATDeviceType

    host = _make_host_with_listener()
    fake_manager = MagicMock()
    fake_manager.get_nat_type.return_value = (
        NATDeviceType.ENDPOINT_INDEPENDENT,
        NATDeviceType.UNKNOWN,
    )
    host._observed_addr_manager = fake_manager

    tcp_nat, udp_nat = host.get_nat_type()

    fake_manager.get_nat_type.assert_called_once_with()
    assert tcp_nat == NATDeviceType.ENDPOINT_INDEPENDENT
    assert udp_nat == NATDeviceType.UNKNOWN


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
