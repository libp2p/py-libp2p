"""Tests for the ObservedAddrManager."""

from __future__ import annotations

from unittest.mock import MagicMock

from multiaddr import Multiaddr

from libp2p.host.observed_addr_manager import (
    _ADDR_CACHE_SIZE,
    ACTIVATION_THRESHOLD,
    MAX_EXTERNAL_ADDRS_PER_LOCAL,
    NATDeviceType,
    ObservedAddrManager,
    extract_thin_waist,
    has_consistent_transport,
    is_valid_observation,
    observer_group,
)

# ---------------------------------------------------------------------------
# Helper: create a mock INetConn with a configurable remote address.
# ---------------------------------------------------------------------------

# Keep all mock connections alive so that id() values are never reused
# within the test session.  ObservedAddrManager keys on id(conn), which
# is only unique while the object exists.
_LIVE_CONNS: list[MagicMock] = []


def _make_conn(
    remote_ip: str = "10.0.0.1", remote_port: int = 12345, is_closed: bool = False
) -> MagicMock:
    conn = MagicMock(spec=[])
    conn.muxed_conn = MagicMock()
    conn.muxed_conn.get_remote_address = MagicMock(
        return_value=(remote_ip, remote_port)
    )
    conn.is_closed = is_closed
    _LIVE_CONNS.append(conn)
    return conn


# ---------------------------------------------------------------------------
# extract_thin_waist
# ---------------------------------------------------------------------------


def test_extract_thin_waist_ipv4_tcp():
    ma = Multiaddr(
        "/ip4/1.2.3.4/tcp/4001/p2p/QmcgpsyWgH8Y8ajJz1Cu72KnS5uo2Aa2LpzU7kinSupNKC"
    )
    result = extract_thin_waist(ma)
    assert result is not None
    tw, rest = result
    assert str(tw) == "/ip4/1.2.3.4/tcp/4001"
    assert "/p2p/" in rest


def test_extract_thin_waist_ipv6_udp():
    ma = Multiaddr("/ip6/::1/udp/4001/quic-v1")
    result = extract_thin_waist(ma)
    assert result is not None
    tw, rest = result
    assert str(tw) == "/ip6/::1/udp/4001"
    assert "quic-v1" in rest


# ---------------------------------------------------------------------------
# observer_group
# ---------------------------------------------------------------------------


def test_observer_group_ipv4():
    assert observer_group(("192.168.1.1", 5000)) == "192.168.1.1"


def test_observer_group_ipv6():
    group = observer_group(("2001:db8:abcd:0012::1", 5000))
    # /56 prefix — the host part is zeroed out.
    assert group == "2001:db8:abcd::"


# ---------------------------------------------------------------------------
# is_valid_observation
# ---------------------------------------------------------------------------


def test_loopback_rejected():
    obs = Multiaddr("/ip4/127.0.0.1/tcp/4001")
    assert is_valid_observation(obs) is False


def test_relay_rejected():
    obs = Multiaddr("/ip4/1.2.3.4/tcp/4001/p2p-circuit")
    assert is_valid_observation(obs) is False


def test_valid_observation():
    obs = Multiaddr("/ip4/1.2.3.4/tcp/4001")
    assert is_valid_observation(obs) is True


# ---------------------------------------------------------------------------
# ObservedAddrManager – record / confirm / remove
# ---------------------------------------------------------------------------


def test_record_and_confirm():
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    observed = Multiaddr("/ip4/1.2.3.4/tcp/4001")

    conns = []
    for i in range(ACTIVATION_THRESHOLD):
        c = _make_conn(remote_ip=f"10.0.0.{i + 1}")
        conns.append(c)
        mgr.record_observation(c, observed, local)

    addrs = mgr.addrs()
    assert any(str(a) == "/ip4/1.2.3.4/tcp/4001" for a in addrs)


def test_below_threshold():
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    observed = Multiaddr("/ip4/1.2.3.4/tcp/4001")

    for i in range(ACTIVATION_THRESHOLD - 1):
        c = _make_conn(remote_ip=f"10.0.0.{i + 1}")
        mgr.record_observation(c, observed, local)

    assert mgr.addrs() == []


def test_duplicate_observer():
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    observed = Multiaddr("/ip4/1.2.3.4/tcp/4001")

    # Same IP, different connections — should count as 1 observer.
    for _ in range(ACTIVATION_THRESHOLD):
        c = _make_conn(remote_ip="10.0.0.1")
        mgr.record_observation(c, observed, local)

    assert mgr.addrs() == []


def test_remove_conn_decrements():
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    observed = Multiaddr("/ip4/1.2.3.4/tcp/4001")

    conns = []
    for i in range(ACTIVATION_THRESHOLD):
        c = _make_conn(remote_ip=f"10.0.0.{i + 1}")
        conns.append(c)
        mgr.record_observation(c, observed, local)

    # Confirmed.
    assert len(mgr.addrs()) > 0

    # Remove one — drops below threshold.
    mgr.remove_conn(conns[0])
    assert mgr.addrs() == []


def test_max_external_addrs():
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]

    # Register MAX + 1 different external addresses, each with enough observers.
    for ext_idx in range(MAX_EXTERNAL_ADDRS_PER_LOCAL + 1):
        observed = Multiaddr(f"/ip4/1.2.3.{ext_idx}/tcp/4001")
        for obs_idx in range(ACTIVATION_THRESHOLD):
            c = _make_conn(remote_ip=f"10.{ext_idx}.0.{obs_idx + 1}")
            mgr.record_observation(c, observed, local)

    addrs = mgr.addrs()
    # Each external thin waist produces exactly 1 addr (no rest suffixes),
    # so we expect at most MAX_EXTERNAL_ADDRS_PER_LOCAL.
    assert len(addrs) <= MAX_EXTERNAL_ADDRS_PER_LOCAL


def test_wildcard_matching():
    """Local 0.0.0.0 matches any IPv4 observation."""
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    observed = Multiaddr("/ip4/99.88.77.66/tcp/4001")

    for i in range(ACTIVATION_THRESHOLD):
        c = _make_conn(remote_ip=f"10.0.0.{i + 1}")
        mgr.record_observation(c, observed, local)

    addrs = mgr.addrs()
    assert any(str(a) == "/ip4/99.88.77.66/tcp/4001" for a in addrs)


def test_address_inference():
    """Listen /ip4/0.0.0.0/tcp/4001/ws → infer /ip4/1.2.3.4/tcp/4001/ws."""
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001/ws")]
    observed = Multiaddr("/ip4/1.2.3.4/tcp/4001")

    for i in range(ACTIVATION_THRESHOLD):
        c = _make_conn(remote_ip=f"10.0.0.{i + 1}")
        mgr.record_observation(c, observed, local)

    addrs = mgr.addrs()
    addr_strs = [str(a) for a in addrs]
    assert "/ip4/1.2.3.4/tcp/4001/ws" in addr_strs


# ---------------------------------------------------------------------------
# Step 1: Observer count tracks connections (counter, not set)
# ---------------------------------------------------------------------------


def test_observer_count_tracks_connections():
    """Two conns from same subnet: disconnect 1, observer should remain."""
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    observed = Multiaddr("/ip4/1.2.3.4/tcp/4001")

    # We need ACTIVATION_THRESHOLD distinct observer groups to confirm.
    # Use (ACTIVATION_THRESHOLD - 1) unique IPs, plus 2 conns from same IP.
    conns = []
    for i in range(ACTIVATION_THRESHOLD - 1):
        c = _make_conn(remote_ip=f"10.0.0.{i + 1}")
        conns.append(c)
        mgr.record_observation(c, observed, local)

    # Two more connections from the same IP (same observer group).
    c_dup1 = _make_conn(remote_ip=f"10.0.0.{ACTIVATION_THRESHOLD}")
    c_dup2 = _make_conn(remote_ip=f"10.0.0.{ACTIVATION_THRESHOLD}")
    mgr.record_observation(c_dup1, observed, local)
    mgr.record_observation(c_dup2, observed, local)

    # Should be confirmed (ACTIVATION_THRESHOLD unique groups).
    assert len(mgr.addrs()) > 0

    # Disconnect one of the duplicate-group connections.
    mgr.remove_conn(c_dup1)

    # Observer group should still be counted — address remains confirmed.
    assert len(mgr.addrs()) > 0


# ---------------------------------------------------------------------------
# Step 2: Same observation short-circuit
# ---------------------------------------------------------------------------


def test_same_observation_shortcircuit():
    """Same observation twice from same conn should not double-count."""
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    observed = Multiaddr("/ip4/1.2.3.4/tcp/4001")

    c = _make_conn(remote_ip="10.0.0.1")
    mgr.record_observation(c, observed, local)
    mgr.record_observation(c, observed, local)  # same observation again

    # Should only have 1 observer group with count 1.
    ext_map = mgr._external_addrs.get("/ip4/0.0.0.0/tcp/4001", {})
    observers = ext_map.get("/ip4/1.2.3.4/tcp/4001", {})
    total = sum(observers.values())
    assert total == 1


# ---------------------------------------------------------------------------
# Step 3: Closed connection is skipped
# ---------------------------------------------------------------------------


def test_is_closed_skipped():
    """Closed connection should not record observation."""
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    observed = Multiaddr("/ip4/1.2.3.4/tcp/4001")

    c = _make_conn(remote_ip="10.0.0.1", is_closed=True)
    mgr.record_observation(c, observed, local)

    assert mgr._external_addrs == {}


# ---------------------------------------------------------------------------
# Step 4: NAT64 address rejected
# ---------------------------------------------------------------------------


def test_nat64_rejected():
    """Addresses in 64:ff9b::/96 should be rejected."""
    # 1.2.3.4 mapped to NAT64 prefix: 64:ff9b::102:304
    obs = Multiaddr("/ip6/64:ff9b::102:304/tcp/4001")
    assert is_valid_observation(obs) is False


# ---------------------------------------------------------------------------
# Step 5a: Configurable threshold
# ---------------------------------------------------------------------------


def test_addrs_with_min_observers():
    """addrs(min_observers=1) returns with fewer observers."""
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    observed = Multiaddr("/ip4/1.2.3.4/tcp/4001")

    c = _make_conn(remote_ip="10.0.0.1")
    mgr.record_observation(c, observed, local)

    # Default threshold should not return it.
    assert mgr.addrs() == []
    # But min_observers=1 should.
    assert len(mgr.addrs(min_observers=1)) > 0
    assert any(str(a) == "/ip4/1.2.3.4/tcp/4001" for a in mgr.addrs(min_observers=1))


# ---------------------------------------------------------------------------
# Step 5c: addrs_for
# ---------------------------------------------------------------------------


def test_addrs_for():
    """Per-listen-address querying."""
    mgr = ObservedAddrManager()
    local_tcp = Multiaddr("/ip4/0.0.0.0/tcp/4001")
    local_udp = Multiaddr("/ip4/0.0.0.0/udp/5001")
    local = [local_tcp, local_udp]

    observed_tcp = Multiaddr("/ip4/1.2.3.4/tcp/4001")
    observed_udp = Multiaddr("/ip4/5.6.7.8/udp/5001")

    for i in range(ACTIVATION_THRESHOLD):
        c1 = _make_conn(remote_ip=f"10.0.0.{i + 1}")
        mgr.record_observation(c1, observed_tcp, local)
        c2 = _make_conn(remote_ip=f"10.1.0.{i + 1}")
        mgr.record_observation(c2, observed_udp, local)

    tcp_addrs = mgr.addrs_for(local_tcp)
    udp_addrs = mgr.addrs_for(local_udp)

    tcp_strs = [str(a) for a in tcp_addrs]
    udp_strs = [str(a) for a in udp_addrs]

    assert "/ip4/1.2.3.4/tcp/4001" in tcp_strs
    assert "/ip4/5.6.7.8/udp/5001" in udp_strs
    # TCP query should not return UDP addresses.
    assert "/ip4/5.6.7.8/udp/5001" not in tcp_strs

    # Query with rest suffix: only that suffix should appear (Go parity).
    local_ws = Multiaddr("/ip4/0.0.0.0/tcp/4001/ws")
    ws_addrs = mgr.addrs_for(local_ws)
    ws_strs = [str(a) for a in ws_addrs]
    assert "/ip4/1.2.3.4/tcp/4001/ws" in ws_strs
    # Bare TW should NOT appear when queried with a rest suffix.
    assert "/ip4/1.2.3.4/tcp/4001" not in ws_strs


# ---------------------------------------------------------------------------
# Step 6: Sorting tiebreaker (lexicographic)
# ---------------------------------------------------------------------------


def test_sorting_tiebreaker():
    """Equal-count addrs should be in lexicographic order."""
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]

    # Register 3 external addrs with same observer count.
    ext_ips = ["1.2.3.4", "1.2.3.2", "1.2.3.3"]
    for ext_ip in ext_ips:
        observed = Multiaddr(f"/ip4/{ext_ip}/tcp/4001")
        for i in range(ACTIVATION_THRESHOLD):
            c = _make_conn(remote_ip=f"10.{ext_ips.index(ext_ip)}.0.{i + 1}")
            mgr.record_observation(c, observed, local)

    addrs = mgr.addrs()
    addr_strs = [str(a) for a in addrs]
    # All should be present and in lexicographic order of the TW string.
    assert addr_strs == sorted(addr_strs)


# ---------------------------------------------------------------------------
# Step 7: NAT type detection
# ---------------------------------------------------------------------------


def test_get_nat_type_unknown():
    """Too few observations → UNKNOWN."""
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    observed = Multiaddr("/ip4/1.2.3.4/tcp/4001")

    # Only a couple of observations — not enough for classification.
    for i in range(2):
        c = _make_conn(remote_ip=f"10.0.0.{i + 1}")
        mgr.record_observation(c, observed, local)

    tcp_nat, udp_nat = mgr.get_nat_type()
    assert tcp_nat == NATDeviceType.UNKNOWN
    assert udp_nat == NATDeviceType.UNKNOWN


def test_get_nat_type_independent():
    """Concentrated observations → ENDPOINT_INDEPENDENT (cone NAT)."""
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    observed = Multiaddr("/ip4/1.2.3.4/tcp/4001")

    # Many observations to a single external address.
    # Need >= 3 * MAX_EXTERNAL_ADDRS_PER_LOCAL = 9 total observations.
    for i in range(12):
        c = _make_conn(remote_ip=f"10.0.{i // 256}.{i % 256 + 1}")
        mgr.record_observation(c, observed, local)

    tcp_nat, udp_nat = mgr.get_nat_type()
    assert tcp_nat == NATDeviceType.ENDPOINT_INDEPENDENT
    assert udp_nat == NATDeviceType.UNKNOWN  # no UDP observations


def test_get_nat_type_dependent():
    """Spread observations → ENDPOINT_DEPENDENT (symmetric NAT)."""
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]

    # Spread observations across many different external addresses.
    # Each external addr gets 1 observer → no concentration.
    for i in range(12):
        observed = Multiaddr(f"/ip4/1.2.3.{i}/tcp/4001")
        c = _make_conn(remote_ip=f"10.0.{i // 256}.{i % 256 + 1}")
        mgr.record_observation(c, observed, local)

    tcp_nat, udp_nat = mgr.get_nat_type()
    assert tcp_nat == NATDeviceType.ENDPOINT_DEPENDENT
    assert udp_nat == NATDeviceType.UNKNOWN


def test_get_nat_type_skips_mixed_transport_bucket():
    """
    White-box test for the defensive TCP/UDP skip guard in
    ``ObservedAddrManager.get_nat_type``.

    Normal flow cannot produce a mixed-transport bucket because
    ``record_observation`` routes through ``_match_local_thin_waist`` +
    ``has_consistent_transport``. We bypass that invariant by poking
    ``_external_addrs`` directly to simulate a future refactor leaking a
    stray entry of the opposite transport into a bucket.

    This test is designed so the result *differs* between guarded and
    unguarded implementations:

    * Bucket is tagged TCP (first inserted key is ``/tcp/``).
    * Real TCP observations are spread across 12 distinct external addresses
      with 1 observer each → alone classifies as ``ENDPOINT_DEPENDENT``.
    * A stray ``/udp/`` entry with 12 concentrated observers is inserted.
    * Without the guard, the UDP count [12] would be absorbed into
      ``tcp_counts`` and the 50% concentration rule would flip the result
      to ``ENDPOINT_INDEPENDENT`` — a silent misclassification.
    * With the guard, the stray UDP entry is skipped and TCP stays
      ``ENDPOINT_DEPENDENT``.
    """
    mgr = ObservedAddrManager()

    local_tw_str = "/ip4/0.0.0.0/tcp/4001"
    bucket: dict[str, dict[str, int]] = {}
    # 12 distinct TCP external addrs, 1 observer each → DEPENDENT on its own.
    for i in range(12):
        bucket[f"/ip4/1.2.3.{i}/tcp/4001"] = {f"10.0.0.{i + 1}": 1}
    # Stray concentrated UDP entry — would flip classification without the
    # guard.
    bucket["/ip4/1.2.3.200/udp/4001"] = {f"10.99.0.{i + 1}": 1 for i in range(12)}
    mgr._external_addrs[local_tw_str] = bucket

    tcp_nat, udp_nat = mgr.get_nat_type()

    # TCP: stays DEPENDENT because the guard filtered out the stray UDP entry.
    assert tcp_nat == NATDeviceType.ENDPOINT_DEPENDENT
    # UDP: no legitimate UDP bucket exists, so UDP stays UNKNOWN.
    assert udp_nat == NATDeviceType.UNKNOWN


# ---------------------------------------------------------------------------
# Step 8: has_consistent_transport
# ---------------------------------------------------------------------------


def test_has_consistent_transport():
    """TCP/TCP passes, TCP/UDP fails."""
    tcp_a = Multiaddr("/ip4/1.2.3.4/tcp/4001")
    tcp_b = Multiaddr("/ip4/5.6.7.8/tcp/5001")
    udp_a = Multiaddr("/ip4/1.2.3.4/udp/4001")

    assert has_consistent_transport(tcp_a, tcp_b) is True
    assert has_consistent_transport(tcp_a, udp_a) is False

    # Too few protocols.
    short = Multiaddr("/ip4/1.2.3.4")
    assert has_consistent_transport(tcp_a, short) is False


# ---------------------------------------------------------------------------
# Integration: BasicHost.get_addrs() includes observed addrs
# ---------------------------------------------------------------------------


def test_get_addrs_includes_observed():
    from libp2p import new_swarm
    from libp2p.crypto.rsa import create_new_key_pair
    from libp2p.host.basic_host import BasicHost

    key_pair = create_new_key_pair()
    swarm = new_swarm(key_pair)
    host = BasicHost(swarm)

    # Set up a mock listener so get_transport_addrs returns something.
    mock_transport = MagicMock()
    mock_transport.get_addrs.return_value = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    swarm.listeners = {"tcp": mock_transport}

    observed = Multiaddr("/ip4/1.2.3.4/tcp/4001")
    for i in range(ACTIVATION_THRESHOLD):
        c = _make_conn(remote_ip=f"10.0.0.{i + 1}")
        host._observed_addr_manager.record_observation(
            c, observed, host.get_transport_addrs()
        )

    addrs = host.get_addrs()
    addr_strs = [str(a) for a in addrs]
    assert any("/ip4/1.2.3.4/tcp/4001" in s for s in addr_strs)


# ---------------------------------------------------------------------------
# Multiaddr cache behavior
# ---------------------------------------------------------------------------


def test_addr_cache_invalidation():
    """Cache is populated on addrs() and cleared when an observation is removed."""
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    observed = Multiaddr("/ip4/1.2.3.4/tcp/4001")

    conns = []
    for i in range(ACTIVATION_THRESHOLD):
        c = _make_conn(remote_ip=f"10.0.0.{i + 1}")
        conns.append(c)
        mgr.record_observation(c, observed, local)

    # First call populates the cache.
    addrs1 = mgr.addrs()
    assert len(addrs1) > 0
    assert len(mgr._addr_cache) > 0

    # Second call should return identical results (cache hit path).
    addrs2 = mgr.addrs()
    assert [str(a) for a in addrs1] == [str(a) for a in addrs2]

    # Remove enough connections to drop the external address entirely.
    for c in conns:
        mgr.remove_conn(c)

    # Cache should have been cleared.
    assert len(mgr._addr_cache) == 0

    # addrs() still works correctly after cache clear (cache miss → rebuild).
    assert mgr.addrs() == []


def test_old_observation_replaced():
    """When a connection reports a different observed addr, the old one is replaced."""
    mgr = ObservedAddrManager()
    local = [Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    local_tw_str = "/ip4/0.0.0.0/tcp/4001"
    observed_a = Multiaddr("/ip4/1.2.3.4/tcp/4001")
    observed_b = Multiaddr("/ip4/5.6.7.8/tcp/4001")

    # Record observed_a from ACTIVATION_THRESHOLD distinct connections.
    conns = []
    for i in range(ACTIVATION_THRESHOLD):
        c = _make_conn(remote_ip=f"10.0.0.{i + 1}")
        conns.append(c)
        mgr.record_observation(c, observed_a, local)

    # Address A should be confirmed.
    assert any(str(a) == "/ip4/1.2.3.4/tcp/4001" for a in mgr.addrs())

    # Re-record on the SAME connections with a different observed address B.
    for c in conns:
        mgr.record_observation(c, observed_b, local)

    addrs = mgr.addrs()
    addr_strs = [str(a) for a in addrs]

    # Address A should be gone; address B should be active.
    assert "/ip4/1.2.3.4/tcp/4001" not in addr_strs
    assert "/ip4/5.6.7.8/tcp/4001" in addr_strs

    # Internal state: _conn_observations should all point to B.
    for c in conns:
        _, ext, _ = mgr._conn_observations[id(c)]
        assert ext == "/ip4/5.6.7.8/tcp/4001"

    # Internal state: old external entry should be cleaned up.
    ext_map = mgr._external_addrs.get(local_tw_str, {})
    assert "/ip4/1.2.3.4/tcp/4001" not in ext_map


def test_addr_cache_size_cap():
    """Cache never exceeds _ADDR_CACHE_SIZE entries."""
    mgr = ObservedAddrManager()
    # Insert more entries than the cap via the internal helper.
    for i in range(_ADDR_CACHE_SIZE + 5):
        mgr._cached_multiaddr(f"/ip4/1.2.3.{i}/tcp/4001")

    assert len(mgr._addr_cache) == _ADDR_CACHE_SIZE
