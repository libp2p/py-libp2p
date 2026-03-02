"""
Tests for the capability protocol declarations.

Validates that ``TransportCapabilities``, ``ConnectionCapabilities``, and
``NeedsSetup`` structural protocols correctly detect conforming /
non-conforming objects at runtime.
"""

import pytest

from libp2p.capabilities import (
    ConnectionCapabilities,
    NeedsSetup,
    TransportCapabilities,
)


class _FullCapabilityTransport:
    """Transport that provides both security and muxing."""

    @property
    def provides_security(self) -> bool:
        return True

    @property
    def provides_muxing(self) -> bool:
        return True


class _SecurityOnlyTransport:
    """Transport that provides only security."""

    @property
    def provides_security(self) -> bool:
        return True

    @property
    def provides_muxing(self) -> bool:
        return False


class _MuxingOnlyTransport:
    """Transport that provides only muxing."""

    @property
    def provides_security(self) -> bool:
        return False

    @property
    def provides_muxing(self) -> bool:
        return True


class _PlainTransport:
    """Transport with no capability properties at all."""

    pass


class _FullCapabilityConnection:
    """Connection that is both secure and muxed."""

    @property
    def is_secure(self) -> bool:
        return True

    @property
    def is_muxed(self) -> bool:
        return True


class _InsecureConnection:
    """Connection that is muxed but not secure."""

    @property
    def is_secure(self) -> bool:
        return False

    @property
    def is_muxed(self) -> bool:
        return True


class _PlainConnection:
    """Connection with no capability properties."""

    pass


class _SetupTransport:
    """Transport that needs lifecycle hooks."""

    def set_background_nursery(self, nursery: object) -> None:
        self._nursery = nursery

    def set_swarm(self, swarm: object) -> None:
        self._swarm = swarm


class _PartialSetupTransport:
    """Transport that only implements set_swarm (not full NeedsSetup)."""

    def set_swarm(self, swarm: object) -> None:
        self._swarm = swarm


class TestTransportCapabilities:
    """Verify TransportCapabilities structural protocol detection."""

    def test_full_capability_transport_is_instance(self):
        t = _FullCapabilityTransport()
        assert isinstance(t, TransportCapabilities)

    def test_security_only_transport_is_instance(self):
        t = _SecurityOnlyTransport()
        assert isinstance(t, TransportCapabilities)

    def test_muxing_only_transport_is_instance(self):
        t = _MuxingOnlyTransport()
        assert isinstance(t, TransportCapabilities)

    def test_plain_transport_is_not_instance(self):
        t = _PlainTransport()
        assert not isinstance(t, TransportCapabilities)

    def test_provides_security_value(self):
        assert _FullCapabilityTransport().provides_security is True
        assert _SecurityOnlyTransport().provides_security is True
        assert _MuxingOnlyTransport().provides_security is False

    def test_provides_muxing_value(self):
        assert _FullCapabilityTransport().provides_muxing is True
        assert _SecurityOnlyTransport().provides_muxing is False
        assert _MuxingOnlyTransport().provides_muxing is True

    def test_getattr_fallback_for_plain(self):
        """The canonical usage pattern: getattr(t, 'provides_security', False)."""
        t = _PlainTransport()
        assert getattr(t, "provides_security", False) is False
        assert getattr(t, "provides_muxing", False) is False


class TestConnectionCapabilities:
    """Verify ConnectionCapabilities structural protocol detection."""

    def test_full_capability_connection_is_instance(self):
        c = _FullCapabilityConnection()
        assert isinstance(c, ConnectionCapabilities)

    def test_insecure_connection_is_instance(self):
        c = _InsecureConnection()
        assert isinstance(c, ConnectionCapabilities)

    def test_plain_connection_is_not_instance(self):
        c = _PlainConnection()
        assert not isinstance(c, ConnectionCapabilities)

    def test_is_secure_value(self):
        assert _FullCapabilityConnection().is_secure is True
        assert _InsecureConnection().is_secure is False

    def test_is_muxed_value(self):
        assert _FullCapabilityConnection().is_muxed is True
        assert _InsecureConnection().is_muxed is True

    def test_getattr_fallback_for_plain(self):
        c = _PlainConnection()
        assert getattr(c, "is_secure", False) is False
        assert getattr(c, "is_muxed", False) is False


class TestNeedsSetup:
    """Verify NeedsSetup structural protocol detection."""

    def test_setup_transport_is_instance(self):
        t = _SetupTransport()
        assert isinstance(t, NeedsSetup)

    def test_partial_setup_transport_is_not_instance(self):
        t = _PartialSetupTransport()
        assert not isinstance(t, NeedsSetup)

    def test_plain_transport_is_not_instance(self):
        t = _PlainTransport()
        assert not isinstance(t, NeedsSetup)

    def test_hasattr_detection(self):
        """The canonical usage in swarm.py: hasattr(t, 'set_background_nursery')."""
        s = _SetupTransport()
        assert hasattr(s, "set_background_nursery")
        assert hasattr(s, "set_swarm")

        p = _PlainTransport()
        assert not hasattr(p, "set_background_nursery")
        assert not hasattr(p, "set_swarm")

    def test_set_background_nursery_stores_value(self):
        t = _SetupTransport()
        sentinel = object()
        t.set_background_nursery(sentinel)
        assert t._nursery is sentinel

    def test_set_swarm_stores_value(self):
        t = _SetupTransport()
        sentinel = object()
        t.set_swarm(sentinel)
        assert t._swarm is sentinel


class TestQUICConformance:
    """Verify that the real QUIC transport and connection satisfy the protocols."""

    def test_quic_transport_satisfies_transport_capabilities(self):
        try:
            from libp2p.transport.quic.transport import QUICTransport
        except ImportError:
            pytest.skip("aioquic not installed")

        assert hasattr(QUICTransport, "provides_security")
        assert hasattr(QUICTransport, "provides_muxing")

    def test_quic_connection_satisfies_connection_capabilities(self):
        try:
            from libp2p.transport.quic.connection import QUICConnection
        except ImportError:
            pytest.skip("aioquic not installed")

        assert hasattr(QUICConnection, "is_secure")
        assert hasattr(QUICConnection, "is_muxed")

    def test_quic_transport_satisfies_needs_setup(self):
        try:
            from libp2p.transport.quic.transport import QUICTransport
        except ImportError:
            pytest.skip("aioquic not installed")

        assert hasattr(QUICTransport, "set_background_nursery")
        assert hasattr(QUICTransport, "set_swarm")
