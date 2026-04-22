"""
Tests for entry-point discovery and conditional imports.

Validates:
- ``discover_and_register()`` populates a registry from entry points
- ``discover_transports / discover_security / discover_muxers`` individual scanners
- Entry-point factory functions produce correct provider types
- Conditional import guards (``_HAS_QUIC``, ``_HAS_NOISE``, etc.)
- Built-in factory functions (``_create_tcp_provider``, etc.)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from libp2p.custom_types import TProtocol
from libp2p.entrypoints import (
    EP_GROUP_MUXERS,
    EP_GROUP_SECURITY,
    EP_GROUP_TRANSPORTS,
    discover_and_register,
    discover_muxers,
    discover_security,
    discover_transports,
)
from libp2p.providers import (
    MuxerProvider,
    ProviderRegistry,
    SecurityProvider,
    TransportProvider,
)


class TestEntryPointGroups:
    def test_transport_group(self) -> None:
        assert EP_GROUP_TRANSPORTS == "libp2p.transports"

    def test_security_group(self) -> None:
        assert EP_GROUP_SECURITY == "libp2p.security"

    def test_muxer_group(self) -> None:
        assert EP_GROUP_MUXERS == "libp2p.muxers"


class TestTcpFactory:
    """_create_tcp_provider should return a TransportProvider."""

    def test_creates_transport_provider(self) -> None:
        from libp2p.transport.tcp.tcp import _create_tcp_provider

        tp = _create_tcp_provider()
        assert isinstance(tp, TransportProvider)
        assert tp.protocol_name == "tcp"


class TestYamuxFactory:
    def test_creates_muxer_provider(self) -> None:
        from libp2p.stream_muxer.yamux.yamux import _create_yamux_provider

        mp = _create_yamux_provider()
        assert isinstance(mp, MuxerProvider)
        assert "/yamux" in mp.protocol_id


class TestMplexFactory:
    def test_creates_muxer_provider(self) -> None:
        from libp2p.stream_muxer.mplex.mplex import _create_mplex_provider

        mp = _create_mplex_provider()
        assert isinstance(mp, MuxerProvider)
        assert "/mplex" in mp.protocol_id


class TestNoiseFactory:
    def test_creates_security_provider(self) -> None:
        from libp2p.security.noise.transport import _create_noise_provider

        sp = _create_noise_provider()
        assert isinstance(sp, SecurityProvider)
        assert "/noise" in sp.protocol_id


class TestTlsFactory:
    def test_creates_security_provider(self) -> None:
        from libp2p.security.tls.transport import _create_tls_provider

        sp = _create_tls_provider()
        assert isinstance(sp, SecurityProvider)
        assert "/tls" in sp.protocol_id


def _make_ep(name: str, factory: object) -> MagicMock:
    """Create a mock entry point."""
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = factory
    return ep


class TestDiscoverAndRegister:
    """Tests using mocked importlib.metadata.entry_points."""

    def test_discovers_all_types(self) -> None:
        """Simulates entry points returning one of each type."""
        tp = TransportProvider("fake-tcp", MagicMock())
        sp = SecurityProvider(TProtocol("/fake-noise"), MagicMock())
        mp = MuxerProvider(TProtocol("/fake-yamux"), MagicMock())

        def mock_entry_points(group: str) -> list[MagicMock]:
            if group == EP_GROUP_TRANSPORTS:
                return [_make_ep("fake-tcp", lambda: tp)]
            elif group == EP_GROUP_SECURITY:
                return [_make_ep("fake-noise", lambda: sp)]
            elif group == EP_GROUP_MUXERS:
                return [_make_ep("fake-yamux", lambda: mp)]
            return []

        with patch(
            "libp2p.entrypoints.entry_points",
            side_effect=mock_entry_points,
            create=True,
        ):
            with patch("libp2p.entrypoints._load_entry_points") as mock_load:
                mock_load.side_effect = lambda group: [
                    (ep.name, ep.load()) for ep in mock_entry_points(group)
                ]

                reg = discover_and_register()

        assert len(reg.get_transports()) == 1
        assert len(reg.get_security_providers()) == 1
        assert len(reg.get_muxer_providers()) == 1

    def test_uses_existing_registry(self) -> None:
        """When given an existing registry, populates it."""
        reg = ProviderRegistry()
        reg.register_transport(TransportProvider("existing", MagicMock()))

        with patch("libp2p.entrypoints._load_entry_points", return_value=[]):
            result = discover_and_register(reg)

        assert result is reg
        assert len(result.get_transports()) == 1

    def test_creates_new_registry_when_none(self) -> None:
        with patch("libp2p.entrypoints._load_entry_points", return_value=[]):
            reg = discover_and_register()
        assert isinstance(reg, ProviderRegistry)

    def test_skips_bad_entry_point(self) -> None:
        """A broken entry point is skipped, not fatal."""

        def bad_load(group: str) -> list[tuple[str, object]]:
            if group == EP_GROUP_TRANSPORTS:

                def _bad() -> None:
                    raise RuntimeError("broken plugin")

                return [("broken", _bad)]
            return []

        with patch("libp2p.entrypoints._load_entry_points", side_effect=bad_load):
            reg = discover_and_register()

        assert len(reg.get_transports()) == 0

    def test_skips_wrong_type(self) -> None:
        """An entry point that returns the wrong type is skipped."""

        def wrong_type_load(group: str) -> list[tuple[str, object]]:
            if group == EP_GROUP_TRANSPORTS:
                return [("wrong", lambda: "not a provider")]
            return []

        with patch(
            "libp2p.entrypoints._load_entry_points", side_effect=wrong_type_load
        ):
            reg = discover_and_register()

        assert len(reg.get_transports()) == 0


class TestConditionalImportFlags:
    """Verify that _HAS_* flags are defined in libp2p.__init__."""

    def test_has_quic_flag_exists(self) -> None:
        import libp2p

        assert hasattr(libp2p, "_HAS_QUIC")
        assert isinstance(libp2p._HAS_QUIC, bool)

    def test_has_noise_flag_exists(self) -> None:
        import libp2p

        assert hasattr(libp2p, "_HAS_NOISE")
        assert isinstance(libp2p._HAS_NOISE, bool)

    def test_has_tls_flag_exists(self) -> None:
        import libp2p

        assert hasattr(libp2p, "_HAS_TLS")
        assert isinstance(libp2p._HAS_TLS, bool)

    def test_has_yamux_flag_exists(self) -> None:
        import libp2p

        assert hasattr(libp2p, "_HAS_YAMUX")
        assert isinstance(libp2p._HAS_YAMUX, bool)

    def test_has_mplex_flag_exists(self) -> None:
        import libp2p

        assert hasattr(libp2p, "_HAS_MPLEX")
        assert isinstance(libp2p._HAS_MPLEX, bool)

    def test_all_flags_true_in_full_install(self) -> None:
        """In a full install, all extras should be available."""
        import libp2p

        assert libp2p._HAS_QUIC is True
        assert libp2p._HAS_NOISE is True
        assert libp2p._HAS_TLS is True
        assert libp2p._HAS_YAMUX is True
        assert libp2p._HAS_MPLEX is True


class TestIndividualDiscovery:
    def test_discover_transports_empty(self) -> None:
        with patch("libp2p.entrypoints._load_entry_points", return_value=[]):
            result = discover_transports()
        assert result == []

    def test_discover_security_empty(self) -> None:
        with patch("libp2p.entrypoints._load_entry_points", return_value=[]):
            result = discover_security()
        assert result == []

    def test_discover_muxers_empty(self) -> None:
        with patch("libp2p.entrypoints._load_entry_points", return_value=[]):
            result = discover_muxers()
        assert result == []

    def test_discover_transports_with_factory(self) -> None:
        tp = TransportProvider("mock", MagicMock())

        with patch(
            "libp2p.entrypoints._load_entry_points",
            return_value=[("mock", lambda: tp)],
        ):
            result = discover_transports()
        assert len(result) == 1
        assert result[0] is tp

    def test_discover_security_with_factory(self) -> None:
        sp = SecurityProvider(TProtocol("/mock"), MagicMock())

        with patch(
            "libp2p.entrypoints._load_entry_points",
            return_value=[("mock", lambda: sp)],
        ):
            result = discover_security()
        assert len(result) == 1
        assert result[0] is sp

    def test_discover_muxers_with_factory(self) -> None:
        mp = MuxerProvider(TProtocol("/mock"), MagicMock())

        with patch(
            "libp2p.entrypoints._load_entry_points",
            return_value=[("mock", lambda: mp)],
        ):
            result = discover_muxers()
        assert len(result) == 1
        assert result[0] is mp
