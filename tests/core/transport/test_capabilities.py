"""
Tests for transport/connection capability flags and helpers.

Verifies that TCP does not declare provides_secure/provides_muxed, that the
capability helpers behave correctly, and that QUIC transport has the flags
(set in tests/core/transport/quic/test_transport.py).
"""

from libp2p.capabilities import (
    connection_provides_muxed,
    transport_provides_secure_and_muxed,
)
from libp2p.transport.tcp.tcp import TCP


def test_tcp_transport_has_no_capability_flags():
    """TCP does not declare provides_secure or provides_muxed (default upgrade path)."""
    transport = TCP()
    assert getattr(transport, "provides_secure", False) is False
    assert getattr(transport, "provides_muxed", False) is False


def test_transport_provides_secure_and_muxed_false_for_tcp():
    """transport_provides_secure_and_muxed returns False for TCP."""
    transport = TCP()
    assert transport_provides_secure_and_muxed(transport) is False


def test_transport_provides_secure_and_muxed_false_for_plain_object():
    """transport_provides_secure_and_muxed returns False for object without flags."""
    assert transport_provides_secure_and_muxed(object()) is False


def test_transport_provides_secure_and_muxed_true_when_both_set():
    """transport_provides_secure_and_muxed is True only when both flags are True."""

    class WithBoth:
        provides_secure = True
        provides_muxed = True

    assert transport_provides_secure_and_muxed(WithBoth()) is True

    class OnlySecure:
        provides_secure = True
        provides_muxed = False

    assert transport_provides_secure_and_muxed(OnlySecure()) is False

    class OnlyMuxed:
        provides_secure = False
        provides_muxed = True

    assert transport_provides_secure_and_muxed(OnlyMuxed()) is False


def test_connection_provides_muxed_false_for_none():
    """connection_provides_muxed returns False for None."""
    assert connection_provides_muxed(None) is False


def test_connection_provides_muxed_false_without_flag():
    """connection_provides_muxed returns False when provides_muxed is not set."""
    assert connection_provides_muxed(object()) is False


def test_connection_provides_muxed_true_when_set():
    """connection_provides_muxed returns True when provides_muxed is True."""

    class Conn:
        provides_muxed = True

    assert connection_provides_muxed(Conn()) is True
