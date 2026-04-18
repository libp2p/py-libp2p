from collections.abc import Sequence
import logging
from unittest.mock import (
    AsyncMock,
    MagicMock,
)

import pytest
from multiaddr import Multiaddr
from multiaddr.exceptions import MultiaddrError

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
from libp2p.identity.identify.pb.identify_pb2 import (
    Identify as IdentifyMsg,
)
from libp2p.peer.id import ID


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


# ---------------------------------------------------------------------------
# Integration tests for ObservedAddrManager wiring into BasicHost:
# * _identify_peer records observation on the manager (Gap 1)
# * _identify_peer's narrow exception handling (Gap 2)
# * _on_notifee_disconnected cleans up the manager's per-conn state (Gap 3)
# ---------------------------------------------------------------------------


class _BasicHostLogCollector(logging.Handler):
    """Handler that simply collects records into a list."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def basic_host_log_records():
    """
    Capture log records from the ``libp2p.host.basic_host`` logger directly.

    We can't rely on pytest's ``caplog`` (attached at the root logger) because
    ``libp2p/utils/logging.py`` reconfigures the ``libp2p`` hierarchy at
    import time based on the ``LIBP2P_DEBUG`` env var: depending on its value
    it may set ``propagate=False`` on the ``libp2p`` logger (or on specific
    submodule loggers like ``libp2p.host.basic_host``), which breaks
    propagation to root. xdist workers in CI occasionally hit a config where
    propagation is broken by the time the test runs, even if it works under a
    plain ``pytest`` invocation.

    Attaching our own handler directly to the target logger sidesteps every
    one of those failure modes: we don't care about propagation or parent
    levels, only whether the logger itself is enabled for DEBUG — which we
    force here.
    """
    target = logging.getLogger("libp2p.host.basic_host")
    handler = _BasicHostLogCollector()
    prev_level = target.level
    prev_disabled = target.disabled
    target.setLevel(logging.DEBUG)
    target.disabled = False
    target.addHandler(handler)
    try:
        yield handler.records
    finally:
        target.removeHandler(handler)
        target.setLevel(prev_level)
        target.disabled = prev_disabled


def _prepare_identify_host(
    monkeypatch: pytest.MonkeyPatch, observed_addr_bytes: bytes
) -> tuple[BasicHost, ID, MagicMock]:
    """
    Build a BasicHost wired up just enough to run ``_identify_peer`` against a
    canned ``IdentifyMsg`` payload for a single fake connection.

    Returns ``(host, peer_id, swarm_conn)``. ``host._observed_addr_manager`` is
    left as the real instance — individual tests should replace it with a mock
    if they want to assert on it.
    """
    host = _make_host_with_listener(announce_addrs=None)
    peer_id = host.get_id()

    swarm_conn = MagicMock()
    swarm_conn.muxed_conn = MagicMock()
    swarm_conn.muxed_conn.peer_id = peer_id
    swarm_conn.muxed_conn.get_remote_address = MagicMock(
        return_value=("10.0.0.1", 4001)
    )
    swarm_conn.is_closed = False
    swarm_conn.event_started = None  # no gating on connect event in tests

    monkeypatch.setattr(host._network, "get_connections", lambda pid: [swarm_conn])

    fake_stream = MagicMock()
    fake_stream.reset = AsyncMock()
    fake_stream.close = AsyncMock()
    host.new_stream = AsyncMock(return_value=fake_stream)

    msg = IdentifyMsg(observed_addr=observed_addr_bytes)
    msg_bytes = msg.SerializeToString()

    async def fake_read(stream, use_varint_format=True):
        return msg_bytes

    async def fake_update(peerstore, peer_id, identify_msg):
        return None

    monkeypatch.setattr(
        "libp2p.host.basic_host.read_length_prefixed_protobuf", fake_read
    )
    monkeypatch.setattr(
        "libp2p.host.basic_host._update_peerstore_from_identify", fake_update
    )

    return host, peer_id, swarm_conn


@pytest.mark.trio
async def test_identify_peer_records_observation(monkeypatch):
    """Gap 1: _identify_peer forwards the peer's observed_addr to the manager."""
    observed = Multiaddr("/ip4/5.6.7.8/tcp/4001")
    host, peer_id, swarm_conn = _prepare_identify_host(monkeypatch, observed.to_bytes())
    fake_manager = MagicMock()
    host._observed_addr_manager = fake_manager

    await host._identify_peer(peer_id, reason="test")

    fake_manager.record_observation.assert_called_once()
    args, _kwargs = fake_manager.record_observation.call_args
    passed_conn, passed_observed, passed_locals = args
    assert passed_conn is swarm_conn
    assert str(passed_observed) == "/ip4/5.6.7.8/tcp/4001"
    # Third arg must be the current list of transport addrs.
    assert list(passed_locals) == host.get_transport_addrs()


@pytest.mark.trio
async def test_identify_peer_swallows_multiaddr_error(
    monkeypatch, basic_host_log_records
):
    """
    Gap 2a: a ``MultiaddrError`` raised while recording the observation must
    be caught and logged at DEBUG; nothing propagates out of _identify_peer.
    We use a well-formed multiaddr and make ``record_observation`` raise —
    real-world malformed byte payloads surface the same exception class, but
    the ``multiaddr`` library constructs lazily and only raises in ``str()``.
    """
    observed = Multiaddr("/ip4/5.6.7.8/tcp/4001")
    host, peer_id, _ = _prepare_identify_host(monkeypatch, observed.to_bytes())
    fake_manager = MagicMock()
    fake_manager.record_observation.side_effect = MultiaddrError(
        "malformed observed_addr"
    )
    host._observed_addr_manager = fake_manager

    # Should not raise.
    await host._identify_peer(peer_id, reason="test")

    fake_manager.record_observation.assert_called_once()
    matching = [
        r
        for r in basic_host_log_records
        if "ignoring malformed observed_addr" in r.getMessage()
    ]
    assert matching, (
        f"expected a DEBUG log for MultiaddrError path; got "
        f"{[(r.levelname, r.getMessage()) for r in basic_host_log_records]}"
    )
    assert matching[0].levelno == logging.DEBUG


@pytest.mark.trio
async def test_identify_peer_swallows_value_error(monkeypatch, basic_host_log_records):
    """
    Gap 2b: record_observation raising ValueError must be caught and logged at
    DEBUG. Nothing propagates out of _identify_peer.
    """
    observed = Multiaddr("/ip4/5.6.7.8/tcp/4001")
    host, peer_id, _ = _prepare_identify_host(monkeypatch, observed.to_bytes())
    fake_manager = MagicMock()
    fake_manager.record_observation.side_effect = ValueError("bogus bytes")
    host._observed_addr_manager = fake_manager

    await host._identify_peer(peer_id, reason="test")

    fake_manager.record_observation.assert_called_once()
    matching = [
        r
        for r in basic_host_log_records
        if "ignoring invalid observed_addr" in r.getMessage()
    ]
    assert matching, (
        f"expected a DEBUG log for ValueError path; got "
        f"{[(r.levelname, r.getMessage()) for r in basic_host_log_records]}"
    )
    assert matching[0].levelno == logging.DEBUG


@pytest.mark.trio
async def test_identify_peer_warns_on_unexpected_error(
    monkeypatch, basic_host_log_records
):
    """
    Gap 2c: any other exception from record_observation must be caught and
    surfaced at WARNING level with a traceback, not swallowed silently.
    """
    observed = Multiaddr("/ip4/5.6.7.8/tcp/4001")
    host, peer_id, _ = _prepare_identify_host(monkeypatch, observed.to_bytes())
    fake_manager = MagicMock()
    fake_manager.record_observation.side_effect = RuntimeError("boom")
    host._observed_addr_manager = fake_manager

    await host._identify_peer(peer_id, reason="test")

    fake_manager.record_observation.assert_called_once()
    matching = [
        r
        for r in basic_host_log_records
        if "unexpected failure recording observation" in r.getMessage()
    ]
    assert matching, (
        f"expected a WARNING log for the generic exception path; got "
        f"{[(r.levelname, r.getMessage()) for r in basic_host_log_records]}"
    )
    assert matching[0].levelno == logging.WARNING
    # exc_info=True must have attached the RuntimeError traceback.
    assert matching[0].exc_info is not None
    assert matching[0].exc_info[0] is RuntimeError


def test_on_notifee_disconnected_calls_remove_conn():
    """
    Gap 3: when a peer disconnects, ObservedAddrManager.remove_conn must be
    invoked so per-conn observations are released.
    """
    host = _make_host_with_listener(announce_addrs=None)
    fake_manager = MagicMock()
    host._observed_addr_manager = fake_manager

    peer_id = host.get_id()
    conn = MagicMock()
    conn.muxed_conn = MagicMock()
    conn.muxed_conn.peer_id = peer_id

    # Preload identified_peers so we can also verify the cleanup happens.
    host._identified_peers.add(peer_id)

    host._on_notifee_disconnected(conn)

    fake_manager.remove_conn.assert_called_once_with(conn)
    assert peer_id not in host._identified_peers


def test_on_notifee_disconnected_without_peer_id_is_noop():
    """
    Defensive: if the muxed_conn has no peer_id attribute, the handler must
    short-circuit without touching the manager.
    """
    host = _make_host_with_listener(announce_addrs=None)
    fake_manager = MagicMock()
    host._observed_addr_manager = fake_manager

    conn = MagicMock()
    conn.muxed_conn = MagicMock()
    conn.muxed_conn.peer_id = None

    host._on_notifee_disconnected(conn)

    fake_manager.remove_conn.assert_not_called()
