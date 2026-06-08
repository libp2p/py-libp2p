"""
Unit tests for libp2p.transport.manager.TransportManager.

Tests verify that the TransportManager correctly:
  - Routes dialing to the right transport (TCP, WebSocket, QUIC)
  - Routes listening to the right transport
  - Returns None when no transport matches
  - Ensures TCP does not match WebSocket/QUIC addresses
  - Delegates set_background_nursery / set_swarm to transports that need it
  - Provides has_transport_for() introspection
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from multiaddr import Multiaddr

from libp2p.transport.manager import TransportManager
from libp2p.transport.tcp.tcp import TCP
from libp2p.abc import ITransport


class StubTransport(ITransport):
    """
    Minimal stub transport for unit-testing routing logic.

    ``can_dial`` returns True when ANY protocol name in ``proto_list`` is
    present in the multiaddr's protocol names, and ``can_handle`` is True.

    The TCP-overlap problem (where /tcp/ws matches a tcp-only stub) is handled
    in the tests by registering the TCP stub with ``["tcp"]`` AND relying on
    the real TCP transport's can_dial() for the "does not steal WS" test.
    """

    def __init__(self, proto_list: list[str], *, can_handle: bool = True):
        self._protocols = proto_list
        self._can_handle = can_handle
        self.background_nursery_set: object | None = None
        self.swarm_set: object | None = None

    async def dial(self, maddr: Multiaddr):
        raise NotImplementedError

    def create_listener(self, handler_function):
        raise NotImplementedError

    def can_dial(self, maddr: Multiaddr) -> bool:
        names = {p.name for p in maddr.protocols()}
        return self._can_handle and bool(names.intersection(set(self._protocols)))

    def can_listen(self, maddr: Multiaddr) -> bool:
        return self.can_dial(maddr)

    def protocols(self) -> list[str]:
        return list(self._protocols)

    def set_background_nursery(self, nursery: object) -> None:
        self.background_nursery_set = nursery

    def set_swarm(self, swarm: object) -> None:
        self.swarm_set = swarm


# ---------------------------------------------------------------------------
# Basic routing tests
# ---------------------------------------------------------------------------

class TestTransportManagerRouting:
    def setup_method(self) -> None:
        self.mgr = TransportManager()
        # Use single-protocol lists so each stub only matches its own proto.
        # TCP: only "/tcp/…" addresses (no "/ws" or "/wss" suffix).
        # The real TCP transport's can_dial handles the exclusion; for the
        # stub we keep it simple and register "tcp" only.  The dialing test
        # uses addresses that each have exactly ONE distinguishing protocol.
        self.tcp_stub = StubTransport(["tcp"])
        self.ws_stub = StubTransport(["ws"])      # only "ws" (not "wss")
        self.quic_stub = StubTransport(["quic-v1"])
        self.mgr.add_transports([self.tcp_stub, self.ws_stub, self.quic_stub])

    def test_for_dialing_routes_tcp(self):
        # Pure TCP address: no /ws, no /quic-v1
        t = self.mgr.for_dialing(Multiaddr("/ip4/127.0.0.1/tcp/4001"))
        assert t is self.tcp_stub

    def test_for_dialing_routes_websocket(self):
        # WebSocket address: has /ws
        t = self.mgr.for_dialing(Multiaddr("/ip4/127.0.0.1/tcp/8080/ws"))
        # The tcp_stub's can_dial checks "tcp in names" -> True, so it may be
        # returned first.  For correct routing this test relies on the REAL
        # TCP transport which excludes ws — tested separately.
        # For this stub-based test, register ws_stub BEFORE tcp_stub.
        mgr2 = TransportManager()
        mgr2.add_transports([self.ws_stub, self.tcp_stub])
        t2 = mgr2.for_dialing(Multiaddr("/ip4/127.0.0.1/tcp/8080/ws"))
        assert t2 is self.ws_stub

    def test_for_dialing_routes_quic_v1(self):
        t = self.mgr.for_dialing(Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1"))
        assert t is self.quic_stub

    def test_for_dialing_returns_none_for_unknown(self):
        mgr = TransportManager()
        mgr.add_transport(self.tcp_stub)
        # No transport registered for QUIC-only
        t = mgr.for_dialing(Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1"))
        assert t is None

    def test_for_listening_routes_tcp(self):
        t = self.mgr.for_listening(Multiaddr("/ip4/127.0.0.1/tcp/4001"))
        assert t is self.tcp_stub

    def test_for_listening_routes_websocket(self):
        mgr2 = TransportManager()
        mgr2.add_transports([self.ws_stub, self.tcp_stub])
        t = mgr2.for_listening(Multiaddr("/ip4/127.0.0.1/tcp/8080/ws"))
        assert t is self.ws_stub

    def test_for_listening_returns_none_when_no_match(self):
        mgr = TransportManager()
        mgr.add_transport(self.tcp_stub)
        t = mgr.for_listening(Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1"))
        assert t is None

    def test_first_registered_transport_wins(self):
        """When two transports claim the same protocol, first wins."""
        mgr = TransportManager()
        first = StubTransport(["tcp"])
        second = StubTransport(["tcp"])
        mgr.add_transports([first, second])
        t = mgr.for_dialing(Multiaddr("/ip4/127.0.0.1/tcp/4001"))
        assert t is first

    def test_has_transport_for_true(self):
        assert self.mgr.has_transport_for(Multiaddr("/ip4/127.0.0.1/tcp/4001")) is True

    def test_has_transport_for_false(self):
        mgr = TransportManager()
        mgr.add_transport(self.tcp_stub)
        assert mgr.has_transport_for(Multiaddr("/ip4/127.0.0.1/udp/9/quic-v1")) is False


# ---------------------------------------------------------------------------
# TCP must not match WebSocket or QUIC addresses
# ---------------------------------------------------------------------------

class TestTCPTransportCandidateBehavior:
    """Verify that the real TCP transport correctly rejects ws/quic addresses."""

    def setup_method(self) -> None:
        self.tcp = TCP()

    def test_tcp_matches_pure_tcp(self):
        assert self.tcp.can_dial(Multiaddr("/ip4/127.0.0.1/tcp/4001")) is True

    def test_tcp_rejects_websocket(self):
        assert self.tcp.can_dial(Multiaddr("/ip4/127.0.0.1/tcp/4001/ws")) is False

    def test_tcp_rejects_wss(self):
        assert self.tcp.can_dial(Multiaddr("/ip4/127.0.0.1/tcp/4001/wss")) is False

    def test_tcp_rejects_quic(self):
        assert self.tcp.can_dial(Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1")) is False

    def test_tcp_protocols_list(self):
        assert self.tcp.protocols() == ["tcp"]

    def test_tcp_can_listen_mirrors_can_dial(self):
        assert self.tcp.can_listen(Multiaddr("/ip4/127.0.0.1/tcp/0")) is True
        assert self.tcp.can_listen(Multiaddr("/ip4/127.0.0.1/tcp/0/ws")) is False

    def test_manager_tcp_does_not_steal_ws(self):
        """When both TCP and WS stubs are registered, WS addr must go to WS stub."""
        mgr = TransportManager()
        mgr.add_transport(self.tcp)  # TCP is registered first
        ws_stub = StubTransport(["ws", "wss"])
        mgr.add_transport(ws_stub)
        t = mgr.for_dialing(Multiaddr("/ip4/127.0.0.1/tcp/8080/ws"))
        assert t is ws_stub


# ---------------------------------------------------------------------------
# Nursery / swarm delegation
# ---------------------------------------------------------------------------

class NoLifecycleStub(ITransport):
    """A transport stub that does NOT expose set_background_nursery or set_swarm."""

    def __init__(self, proto_list: list[str]):
        self._protocols = proto_list

    async def dial(self, maddr: Multiaddr):
        raise NotImplementedError

    def create_listener(self, handler_function):
        raise NotImplementedError

    def can_dial(self, maddr: Multiaddr) -> bool:
        names = {p.name for p in maddr.protocols()}
        return bool(names.intersection(set(self._protocols)))

    def can_listen(self, maddr: Multiaddr) -> bool:
        return self.can_dial(maddr)

    def protocols(self) -> list[str]:
        return list(self._protocols)


class TestTransportManagerLifecycle:
    def setup_method(self) -> None:
        self.mgr = TransportManager()
        self.t1 = StubTransport(["tcp"])
        self.t2 = StubTransport(["ws"])
        self.plain = NoLifecycleStub(["quic-v1"])
        self.mgr.add_transports([self.t1, self.t2, self.plain])

    def test_set_background_nursery_delegates_to_all(self):
        fake_nursery = object()
        self.mgr.set_background_nursery(fake_nursery)
        assert self.t1.background_nursery_set is fake_nursery
        assert self.t2.background_nursery_set is fake_nursery
        # plain has no set_background_nursery; must not raise

    def test_set_swarm_delegates_to_all(self):
        fake_swarm = object()
        self.mgr.set_swarm(fake_swarm)
        assert self.t1.swarm_set is fake_swarm
        assert self.t2.swarm_set is fake_swarm

    def test_get_transports_returns_copy(self):
        result = self.mgr.get_transports()
        assert result == [self.t1, self.t2, self.plain]
        # Mutating the returned list must not affect the manager
        result.clear()
        assert len(self.mgr.get_transports()) == 3


# ---------------------------------------------------------------------------
# Empty manager edge cases
# ---------------------------------------------------------------------------

class TestTransportManagerEmpty:
    def test_for_dialing_empty_returns_none(self):
        mgr = TransportManager()
        assert mgr.for_dialing(Multiaddr("/ip4/127.0.0.1/tcp/4001")) is None

    def test_for_listening_empty_returns_none(self):
        mgr = TransportManager()
        assert mgr.for_listening(Multiaddr("/ip4/127.0.0.1/tcp/4001")) is None

    def test_has_transport_for_empty(self):
        mgr = TransportManager()
        assert mgr.has_transport_for(Multiaddr("/ip4/127.0.0.1/tcp/4001")) is False

    def test_set_nursery_empty_does_not_raise(self):
        mgr = TransportManager()
        mgr.set_background_nursery(object())  # Must not raise

    def test_set_swarm_empty_does_not_raise(self):
        mgr = TransportManager()
        mgr.set_swarm(object())  # Must not raise


# ---------------------------------------------------------------------------
# Pre-filter correctness
# ---------------------------------------------------------------------------

class TestTransportManagerPreFilter:
    """Verify the protocol-name pre-filter prevents spurious can_dial calls."""

    def test_can_dial_not_called_when_no_proto_overlap(self):
        """A transport whose protocols() has no overlap should not have can_dial called."""
        mgr = TransportManager()
        tcp = TCP()

        import libp2p.abc as abc_mod
        original_can_dial = tcp.can_dial
        call_count = 0

        def counting_can_dial(maddr):
            nonlocal call_count
            call_count += 1
            return original_can_dial(maddr)

        tcp.can_dial = counting_can_dial  # type: ignore[method-assign]
        mgr.add_transport(tcp)

        # QUIC address has no "tcp" protocol -> pre-filter should block it
        mgr.for_dialing(Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1"))
        assert call_count == 0, (
            "can_dial should NOT be called when no protocol overlap"
        )
