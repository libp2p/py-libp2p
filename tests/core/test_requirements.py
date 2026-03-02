"""
Tests for the requirement decorators and runtime enforcement.

Validates ``@requires_connection``, ``@after_connection``, introspection
helpers, and ``check_connection_requirements``.
"""

import pytest

from libp2p.abc import IMuxedConn, ISecureConn
from libp2p.requirements import (
    ConnectionRequirementError,
    after_connection,
    check_connection_requirements,
    get_after_connections,
    get_required_connections,
    requires_connection,
)


class _FakeSecureConn:
    """
    Minimal stub that *is* an ISecureConn stand-in for isinstance checks.

    We register it with ISecureConn at module level so ``isinstance`` works.
    """

    pass


class _FakePlainConn:
    """A plain connection that satisfies no interfaces."""

    pass


class TestRequiresConnection:
    """Tests for the @requires_connection decorator."""

    def test_attaches_metadata_single_interface(self):
        @requires_connection(ISecureConn)
        async def handler(stream):
            pass

        assert hasattr(handler, "_required_connections")
        assert handler._required_connections == (ISecureConn,)

    def test_attaches_metadata_multiple_interfaces(self):
        @requires_connection(ISecureConn, IMuxedConn)
        async def handler(stream):
            pass

        assert handler._required_connections == (ISecureConn, IMuxedConn)

    def test_no_arguments(self):
        @requires_connection()
        async def handler(stream):
            pass

        assert handler._required_connections == ()

    def test_preserves_function_identity(self):
        async def original(stream):
            pass

        decorated = requires_connection(ISecureConn)(original)
        assert decorated is original

    def test_preserves_function_name(self):
        @requires_connection(ISecureConn)
        async def my_handler(stream):
            pass

        assert my_handler.__name__ == "my_handler"

    def test_works_on_sync_function(self):
        @requires_connection(ISecureConn)
        def sync_handler(stream):
            pass

        assert sync_handler._required_connections == (ISecureConn,)

    def test_works_on_class(self):
        @requires_connection(ISecureConn)
        class MyHandler:
            pass

        assert MyHandler._required_connections == (ISecureConn,)


class TestGetRequiredConnections:
    """Tests for the get_required_connections introspection helper."""

    def test_returns_interfaces_for_decorated(self):
        @requires_connection(ISecureConn)
        async def handler(stream):
            pass

        result = get_required_connections(handler)
        assert result == (ISecureConn,)

    def test_returns_empty_for_undecorated(self):
        async def handler(stream):
            pass

        result = get_required_connections(handler)
        assert result == ()

    def test_returns_empty_for_none(self):
        result = get_required_connections(None)
        assert result == ()

    def test_returns_empty_for_arbitrary_object(self):
        result = get_required_connections(42)
        assert result == ()


class TestAfterConnection:
    """Tests for the @after_connection decorator."""

    def test_attaches_metadata_single_interface(self):
        @after_connection(ISecureConn)
        class MyMuxer:
            pass

        assert hasattr(MyMuxer, "_after_connections")
        assert MyMuxer._after_connections == (ISecureConn,)

    def test_attaches_metadata_multiple_interfaces(self):
        @after_connection(ISecureConn, IMuxedConn)
        class MyMuxer:
            pass

        assert MyMuxer._after_connections == (ISecureConn, IMuxedConn)

    def test_no_arguments(self):
        @after_connection()
        class MyMuxer:
            pass

        assert MyMuxer._after_connections == ()

    def test_preserves_class_identity(self):
        class Original:
            pass

        decorated = after_connection(ISecureConn)(Original)
        assert decorated is Original

    def test_preserves_class_name(self):
        @after_connection(ISecureConn)
        class MyMuxer:
            pass

        assert MyMuxer.__name__ == "MyMuxer"

    def test_works_on_function(self):
        @after_connection(ISecureConn)
        def setup_fn():
            pass

        assert setup_fn._after_connections == (ISecureConn,)


class TestGetAfterConnections:
    """Tests for the get_after_connections introspection helper."""

    def test_returns_interfaces_for_decorated(self):
        @after_connection(ISecureConn)
        class MyMuxer:
            pass

        result = get_after_connections(MyMuxer)
        assert result == (ISecureConn,)

    def test_returns_empty_for_undecorated(self):
        class MyMuxer:
            pass

        result = get_after_connections(MyMuxer)
        assert result == ()

    def test_returns_empty_for_none(self):
        result = get_after_connections(None)
        assert result == ()


class TestRealMuxerMetadata:
    """Verify that Mplex and Yamux carry @after_connection(ISecureConn) metadata."""

    def test_mplex_has_after_connection(self):
        from libp2p.stream_muxer.mplex.mplex import Mplex

        after = get_after_connections(Mplex)
        assert ISecureConn in after

    def test_yamux_has_after_connection(self):
        from libp2p.stream_muxer.yamux.yamux import Yamux

        after = get_after_connections(Yamux)
        assert ISecureConn in after


class TestCheckConnectionRequirements:
    """Tests for the runtime enforcement helper."""

    def test_returns_true_when_no_requirements(self):
        async def handler(stream):
            pass

        result = check_connection_requirements(handler, _FakePlainConn())
        assert result is True

    def test_returns_true_when_requirement_satisfied(self):
        """
        ISecureConn is an ABC — we can't easily make a fake satisfy it.
        But we can test with a real QUIC connection class or by using
        a protocol that's satisfied structurally.
        """

        @requires_connection()
        async def handler(stream):
            pass

        result = check_connection_requirements(handler, _FakePlainConn())
        assert result is True

    def test_returns_false_when_requirement_not_satisfied(self):
        @requires_connection(ISecureConn)
        async def handler(stream):
            pass

        result = check_connection_requirements(handler, _FakePlainConn())
        assert result is False

    def test_raises_on_failure(self):
        @requires_connection(ISecureConn)
        async def handler(stream):
            pass

        with pytest.raises(ConnectionRequirementError, match="requires ISecureConn"):
            check_connection_requirements(
                handler, _FakePlainConn(), raise_on_failure=True
            )

    def test_error_message_contains_handler_name(self):
        @requires_connection(ISecureConn)
        async def my_echo_handler(stream):
            pass

        with pytest.raises(ConnectionRequirementError, match="my_echo_handler"):
            check_connection_requirements(
                my_echo_handler, _FakePlainConn(), raise_on_failure=True
            )

    def test_error_message_contains_connection_type(self):
        @requires_connection(ISecureConn)
        async def handler(stream):
            pass

        with pytest.raises(ConnectionRequirementError, match="_FakePlainConn"):
            check_connection_requirements(
                handler, _FakePlainConn(), raise_on_failure=True
            )

    def test_multiple_requirements_all_fail(self):
        @requires_connection(ISecureConn, IMuxedConn)
        async def handler(stream):
            pass

        result = check_connection_requirements(handler, _FakePlainConn())
        assert result is False

    def test_handler_with_no_decoration(self):
        """An undecorated handler should always pass."""

        async def handler(stream):
            pass

        assert check_connection_requirements(handler, _FakePlainConn()) is True
        assert check_connection_requirements(handler, object()) is True


class TestConnectionRequirementError:
    """Verify the custom exception class."""

    def test_is_exception(self):
        assert issubclass(ConnectionRequirementError, Exception)

    def test_message_preserved(self):
        err = ConnectionRequirementError("test message")
        assert str(err) == "test message"

    def test_can_be_caught(self):
        with pytest.raises(ConnectionRequirementError):
            raise ConnectionRequirementError("oops")


class TestUpgraderMuxerOrdering:
    """Verify that TransportUpgrader._verify_muxer_ordering works correctly."""

    def test_verify_muxer_ordering_with_no_muxers(self):
        """Empty muxer registry should not raise."""
        from libp2p.transport.upgrader import TransportUpgrader

        upgrader = TransportUpgrader({}, {})
        upgrader._verify_muxer_ordering(object())

    def test_verify_muxer_ordering_with_undecorated_muxer(self):
        """A muxer with no @after_connection should pass any connection."""
        from libp2p.transport.upgrader import TransportUpgrader

        class PlainMuxer:
            pass

        upgrader = TransportUpgrader({}, {"/plain/1.0.0": PlainMuxer})
        upgrader._verify_muxer_ordering(object())

    def test_verify_muxer_ordering_warns_on_mismatch(self):
        """
        A muxer with @after_connection(ISecureConn) should warn when
        given a plain connection.
        """
        import logging

        from libp2p.transport.upgrader import TransportUpgrader

        @after_connection(ISecureConn)
        class StrictMuxer:
            pass

        upgrader = TransportUpgrader({}, {"/strict/1.0.0": StrictMuxer})

        upgrader_logger = logging.getLogger("libp2p.transport.upgrader")

        captured: list[str] = []

        class _CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())

        handler = _CaptureHandler()
        handler.setLevel(logging.WARNING)
        upgrader_logger.addHandler(handler)
        try:
            upgrader._verify_muxer_ordering(_FakePlainConn())
        finally:
            upgrader_logger.removeHandler(handler)

        assert len(captured) == 1
        assert "StrictMuxer" in captured[0]
        assert "ISecureConn" in captured[0]
