from __future__ import annotations

from typing import cast
from unittest.mock import Mock

from libp2p.abc import IMuxedConn, ITransport
from libp2p.transport.capabilities import (
    PROVIDES_MUXED_ATTRIBUTE,
    PROVIDES_SECURE_ATTRIBUTE,
    muxed_conn_get_establishment_waiter,
    muxed_conn_has_establishment_wait,
    muxed_conn_has_negotiation_semaphore,
    muxed_conn_has_resource_scope,
    muxed_conn_is_established,
    transport_provides_muxed_connection,
    transport_provides_secure_connection,
    transport_provides_secure_muxed,
)
from libp2p.transport.tcp.tcp import TCP

# -----------------------------------------------------------------------------
# Transport capability helpers
# -----------------------------------------------------------------------------


class TestTransportProvidesSecureConnection:
    """Edge cases for transport_provides_secure_connection()."""

    def test_missing_attribute_returns_false(self):
        """Transport without provides_secure_connection returns False."""

        class NoAttr:
            pass

        transport = cast(ITransport, NoAttr())
        assert transport_provides_secure_connection(transport) is False

    def test_explicit_false_returns_false(self):
        """provides_secure_connection=False returns False."""
        transport = Mock(spec=ITransport)
        transport.provides_secure_connection = False
        assert transport_provides_secure_connection(transport) is False

    def test_explicit_true_returns_true(self):
        """provides_secure_connection=True returns True."""
        transport = Mock(spec=ITransport)
        transport.provides_secure_connection = True
        assert transport_provides_secure_connection(transport) is True

    def test_truthy_non_bool_coerced_to_true(self):
        """Non-bool truthy value (e.g. 1) is coerced to True."""
        transport = Mock(spec=ITransport)
        transport.provides_secure_connection = 1
        assert transport_provides_secure_connection(transport) is True

    def test_falsy_value_returns_false(self):
        """Falsy values (0, "", None) return False."""
        transport = Mock(spec=ITransport)
        transport.provides_secure_connection = 0
        assert transport_provides_secure_connection(transport) is False

    def test_tcp_has_no_secure_capability(self):
        """TCP does not set provides_secure_connection."""
        assert transport_provides_secure_connection(TCP()) is False

    def test_quic_has_secure_capability(self):
        """QUIC transport sets provides_secure_connection=True."""
        from libp2p.crypto.ed25519 import create_new_key_pair
        from libp2p.transport.quic.transport import QUICTransport

        quic = QUICTransport(create_new_key_pair().private_key)
        assert transport_provides_secure_connection(quic) is True


class TestTransportProvidesMuxedConnection:
    """Edge cases for transport_provides_muxed_connection()."""

    def test_missing_attribute_returns_false(self):
        """Transport without provides_muxed_connection returns False."""

        class NoAttr:
            pass

        transport = cast(ITransport, NoAttr())
        assert transport_provides_muxed_connection(transport) is False

    def test_explicit_true_returns_true(self):
        """provides_muxed_connection=True returns True."""
        transport = Mock(spec=ITransport)
        transport.provides_muxed_connection = True
        assert transport_provides_muxed_connection(transport) is True

    def test_explicit_false_returns_false(self):
        """provides_muxed_connection=False returns False."""
        transport = Mock(spec=ITransport)
        transport.provides_muxed_connection = False
        assert transport_provides_muxed_connection(transport) is False

    def test_tcp_has_no_muxed_capability(self):
        """TCP does not set provides_muxed_connection."""
        assert transport_provides_muxed_connection(TCP()) is False

    def test_quic_has_muxed_capability(self):
        """QUIC transport sets provides_muxed_connection=True."""
        from libp2p.crypto.ed25519 import create_new_key_pair
        from libp2p.transport.quic.transport import QUICTransport

        quic = QUICTransport(create_new_key_pair().private_key)
        assert transport_provides_muxed_connection(quic) is True


class TestTransportProvidesSecureMuxed:
    """Edge cases for transport_provides_secure_muxed() (both flags)."""

    def test_both_true_returns_true(self):
        """Both secure and muxed -> True."""
        transport = Mock(spec=ITransport)
        transport.provides_secure_connection = True
        transport.provides_muxed_connection = True
        assert transport_provides_secure_muxed(transport) is True

    def test_secure_only_returns_false(self):
        """Secure but not muxed -> False."""
        transport = Mock(spec=ITransport)
        transport.provides_secure_connection = True
        transport.provides_muxed_connection = False
        assert transport_provides_secure_muxed(transport) is False

    def test_muxed_only_returns_false(self):
        """Muxed but not secure -> False."""
        transport = Mock(spec=ITransport)
        transport.provides_secure_connection = False
        transport.provides_muxed_connection = True
        assert transport_provides_secure_muxed(transport) is False

    def test_neither_returns_false(self):
        """Neither -> False."""
        transport = Mock(spec=ITransport)
        transport.provides_secure_connection = False
        transport.provides_muxed_connection = False
        assert transport_provides_secure_muxed(transport) is False

    def test_quic_returns_true(self):
        """QUIC has both capabilities."""
        from libp2p.crypto.ed25519 import create_new_key_pair
        from libp2p.transport.quic.transport import QUICTransport

        quic = QUICTransport(create_new_key_pair().private_key)
        assert transport_provides_secure_muxed(quic) is True


class TestCapabilityConstants:
    """Attribute names used by transports."""

    def test_constant_values(self):
        """Constants match expected attribute names."""
        assert PROVIDES_SECURE_ATTRIBUTE == "provides_secure_connection"
        assert PROVIDES_MUXED_ATTRIBUTE == "provides_muxed_connection"


# -----------------------------------------------------------------------------
# MuxedConn capability helpers
# -----------------------------------------------------------------------------


class TestMuxedConnHasResourceScope:
    """Edge cases for muxed_conn_has_resource_scope()."""

    def test_callable_set_resource_scope_returns_true(self):
        """Connection with callable set_resource_scope -> True."""
        conn = Mock(spec=IMuxedConn)
        conn.set_resource_scope = Mock()
        assert muxed_conn_has_resource_scope(conn) is True

    def test_no_set_resource_scope_returns_false(self):
        """Connection without set_resource_scope -> False."""

        class NoScope:
            pass

        conn = cast(IMuxedConn, NoScope())
        assert muxed_conn_has_resource_scope(conn) is False

    def test_set_resource_scope_none_not_callable_returns_false(self):
        """Attribute exists but is None (not callable) -> False."""
        conn = Mock(spec=IMuxedConn)
        conn.set_resource_scope = None
        assert muxed_conn_has_resource_scope(conn) is False

    def test_set_resource_scope_not_callable_returns_false(self):
        """Attribute exists but not callable (e.g. int) -> False."""
        conn = Mock(spec=IMuxedConn)
        conn.set_resource_scope = 42
        assert muxed_conn_has_resource_scope(conn) is False


class TestMuxedConnHasEstablishmentWait:
    """Edge cases for muxed_conn_has_establishment_wait()."""

    def test_both_attrs_present_returns_true(self):
        """Both is_established and _connected_event -> True."""
        conn = Mock(spec=IMuxedConn)
        conn.is_established = True
        conn._connected_event = Mock()
        assert muxed_conn_has_establishment_wait(conn) is True

    def test_only_is_established_returns_false(self):
        """Only is_established, no _connected_event -> False."""

        class OnlyEstablished:
            is_established = True

        conn = cast(IMuxedConn, OnlyEstablished())
        assert muxed_conn_has_establishment_wait(conn) is False

    def test_only_connected_event_returns_false(self):
        """Only _connected_event, no is_established -> False."""

        class NoEstablished:
            _connected_event = Mock()

        conn = cast(IMuxedConn, NoEstablished())
        assert muxed_conn_has_establishment_wait(conn) is False

    def test_neither_returns_false(self):
        """Neither attribute -> False."""

        class Neither:
            pass

        conn = cast(IMuxedConn, Neither())
        assert muxed_conn_has_establishment_wait(conn) is False


class TestMuxedConnHasNegotiationSemaphore:
    """Edge cases for muxed_conn_has_negotiation_semaphore()."""

    def test_semaphore_present_and_not_none_returns_true(self):
        """_negotiation_semaphore is not None -> True."""
        conn = Mock(spec=IMuxedConn)
        conn._negotiation_semaphore = object()
        assert muxed_conn_has_negotiation_semaphore(conn) is True

    def test_semaphore_none_returns_false(self):
        """_negotiation_semaphore is None -> False."""
        conn = Mock(spec=IMuxedConn)
        conn._negotiation_semaphore = None
        assert muxed_conn_has_negotiation_semaphore(conn) is False

    def test_no_semaphore_attr_returns_false(self):
        """No _negotiation_semaphore attribute -> False."""

        class NoSem:
            pass

        conn = cast(IMuxedConn, NoSem())
        assert muxed_conn_has_negotiation_semaphore(conn) is False


class TestMuxedConnGetEstablishmentWaiter:
    """Edge cases for muxed_conn_get_establishment_waiter()."""

    def test_returns_connected_event_when_present(self):
        """Returns _connected_event when present."""
        event = Mock()
        conn = Mock(spec=IMuxedConn)
        conn._connected_event = event
        assert muxed_conn_get_establishment_waiter(conn) is event

    def test_returns_none_when_absent(self):
        """Returns None when _connected_event absent."""

        class NoEvent:
            pass

        conn = cast(IMuxedConn, NoEvent())
        assert muxed_conn_get_establishment_waiter(conn) is None


class TestMuxedConnIsEstablished:
    """Edge cases for muxed_conn_is_established()."""

    def test_missing_attr_returns_true(self):
        """No is_established -> True (no wait needed)."""
        conn = Mock(spec=IMuxedConn)
        del conn.is_established
        assert muxed_conn_is_established(conn) is True

    def test_property_true_returns_true(self):
        """is_established=True -> True."""
        conn = Mock(spec=IMuxedConn)
        conn.is_established = True
        assert muxed_conn_is_established(conn) is True

    def test_property_false_returns_false(self):
        """is_established=False -> False."""
        conn = Mock(spec=IMuxedConn)
        conn.is_established = False
        assert muxed_conn_is_established(conn) is False

    def test_callable_returning_true(self):
        """is_established as callable returning True -> True."""
        conn = Mock(spec=IMuxedConn)
        conn.is_established = Mock(return_value=True)
        assert muxed_conn_is_established(conn) is True

    def test_callable_returning_false(self):
        """is_established as callable returning False -> False."""
        conn = Mock(spec=IMuxedConn)
        conn.is_established = Mock(return_value=False)
        assert muxed_conn_is_established(conn) is False

    def test_falsy_non_callable_returns_false(self):
        """is_established=0 or "" -> False."""
        conn = Mock(spec=IMuxedConn)
        conn.is_established = 0
        assert muxed_conn_is_established(conn) is False

    def test_truthy_non_callable_returns_true(self):
        """is_established=1 (truthy) -> True."""
        conn = Mock(spec=IMuxedConn)
        conn.is_established = 1
        assert muxed_conn_is_established(conn) is True
