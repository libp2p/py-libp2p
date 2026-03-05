"""
Tests for the pull-based connection resolver.

Validates:
- ``ConnectionResolver.resolve()`` — outbound dial with transport selection,
  security + muxer upgrade, capability-based skip, fallback on failure.
- ``ConnectionResolver.upgrade_inbound()`` — inbound upgrade path.
- ``ResolvedStack`` — properties and diagnostics.
- Resolution error classes.
"""

from __future__ import annotations

import pytest

from libp2p.custom_types import TProtocol
from libp2p.network.resolver import (
    AllPathsFailedError,
    ConnectionResolver,
    NoTransportError,
    ResolutionError,
    ResolvedStack,
)
from libp2p.peer.id import ID
from libp2p.providers import (
    MuxerProvider,
    ProviderRegistry,
    SecurityProvider,
    TransportProvider,
)
from libp2p.transport.exceptions import (
    MuxerUpgradeFailure,
    SecurityUpgradeFailure,
)


class _StubRawConn:
    async def close(self) -> None:
        pass


class _StubSecureConn:
    def get_remote_peer(self) -> ID:
        return ID(b"\x01\x02")

    async def close(self) -> None:
        pass


class _StubMuxedConn:
    pass


class _StubSecureTransport:
    async def secure_outbound(self, conn: object, peer_id: ID) -> _StubSecureConn:
        return _StubSecureConn()

    async def secure_inbound(self, conn: object) -> _StubSecureConn:
        return _StubSecureConn()


class _FailingSecureTransport:
    async def secure_outbound(self, conn: object, peer_id: ID) -> _StubSecureConn:
        raise ConnectionError("security handshake failed")

    async def secure_inbound(self, conn: object) -> _StubSecureConn:
        raise ConnectionError("security handshake failed")


class _StubMuxerClass:
    def __init__(self, conn: object, peer_id: ID) -> None:
        self.conn = conn
        self.peer_id = peer_id


class _StubTransport:
    async def dial(self, maddr: object) -> _StubRawConn:
        return _StubRawConn()

    async def create_listener(self, handler: object) -> None:
        pass


class _FailingTransport:
    async def dial(self, maddr: object) -> _StubRawConn:
        raise ConnectionError("dial failed")


class _CapableTransport:
    """Transport providing security + muxing (like QUIC)."""

    @property
    def provides_security(self) -> bool:
        return True

    @property
    def provides_muxing(self) -> bool:
        return True

    async def dial(self, maddr: object) -> _StubRawConn:
        return _StubRawConn()


class _ProtoStub:
    """Simple object with a .name attribute."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeMaddr:
    """Fake multiaddr for testing."""

    def __init__(self, proto_names: list[str]) -> None:
        self._proto_names = proto_names

    def protocols(self) -> list[_ProtoStub]:
        return [_ProtoStub(n) for n in self._proto_names]


def _tcp_maddr() -> _FakeMaddr:
    return _FakeMaddr(["ip4", "tcp"])


def _quic_maddr() -> _FakeMaddr:
    return _FakeMaddr(["ip4", "udp", "quic"])


def _peer_id() -> ID:
    return ID(b"\x01\x02\x03")


def _build_registry(
    *,
    transport: object | None = None,
    transport_name: str = "tcp",
    sec_transport: object | None = None,
    muxer_class: object | None = None,
    capable_transport: bool = False,
) -> ProviderRegistry:
    """Build a ProviderRegistry with optional components registered."""
    reg = ProviderRegistry()

    if capable_transport:
        tp = TransportProvider("quic", _CapableTransport())
        reg.register_transport(tp)
    elif transport is not None:
        tp = TransportProvider(transport_name, transport)
        reg.register_transport(tp)

    if sec_transport is not None:
        sp = SecurityProvider(TProtocol("/noise"), sec_transport)
        reg.register_security(sp)

    if muxer_class is not None:
        mp = MuxerProvider(TProtocol("/yamux/1.0.0"), muxer_class)
        reg.register_muxer(mp)

    return reg


class TestResolvedStack:
    """Tests for the ResolvedStack dataclass."""

    def test_top_connection_muxed(self) -> None:
        stack = ResolvedStack(
            raw_conn=_StubRawConn(),
            secure_conn=_StubSecureConn(),
            muxed_conn=_StubMuxedConn(),
        )
        assert stack.top_connection is stack.muxed_conn

    def test_top_connection_secure(self) -> None:
        stack = ResolvedStack(
            raw_conn=_StubRawConn(),
            secure_conn=_StubSecureConn(),
        )
        assert stack.top_connection is stack.secure_conn

    def test_top_connection_raw(self) -> None:
        stack = ResolvedStack(raw_conn=_StubRawConn())
        assert stack.top_connection is stack.raw_conn

    def test_top_connection_empty(self) -> None:
        stack = ResolvedStack()
        assert stack.top_connection is None

    def test_describes_full_stack(self) -> None:
        stack = ResolvedStack(
            transport_provider=TransportProvider("tcp", _StubTransport()),
            security_provider=SecurityProvider(
                TProtocol("/noise"), _StubSecureTransport()
            ),
            muxer_provider=MuxerProvider(TProtocol("/yamux/1.0.0"), _StubMuxerClass),
        )
        desc = stack.describes()
        assert "tcp" in desc
        assert "/noise" in desc
        assert "/yamux/1.0.0" in desc

    def test_describes_builtin_security(self) -> None:
        stack = ResolvedStack(
            transport_provider=TransportProvider("quic", _CapableTransport()),
            skipped_security=True,
            skipped_muxer=True,
        )
        desc = stack.describes()
        assert "builtin" in desc

    def test_describes_empty(self) -> None:
        stack = ResolvedStack()
        assert stack.describes() == "(empty)"


class TestResolutionErrors:
    """Tests for resolution error classes."""

    def test_no_transport_error_is_resolution_error(self) -> None:
        assert issubclass(NoTransportError, ResolutionError)

    def test_all_paths_failed_stores_failures(self) -> None:
        failures = [("tcp", ConnectionError("fail1")), ("quic", TimeoutError("fail2"))]
        err = AllPathsFailedError(failures)
        assert err.failures == failures
        assert "tcp" in str(err)
        assert "quic" in str(err)

    def test_resolution_error_is_exception(self) -> None:
        assert issubclass(ResolutionError, Exception)


class TestResolverHappyPath:
    """Tests for successful resolution."""

    @pytest.mark.trio
    async def test_resolve_full_stack_tcp(self) -> None:
        """TCP transport → security upgrade → muxer upgrade."""
        reg = _build_registry(
            transport=_StubTransport(),
            sec_transport=_StubSecureTransport(),
            muxer_class=_StubMuxerClass,
        )
        resolver = ConnectionResolver(reg)
        stack = await resolver.resolve(_tcp_maddr(), _peer_id())

        assert stack.raw_conn is not None
        assert stack.secure_conn is not None
        assert stack.muxed_conn is not None
        assert not stack.skipped_security
        assert not stack.skipped_muxer
        assert stack.transport_provider is not None
        assert stack.security_provider is not None
        assert stack.muxer_provider is not None

    @pytest.mark.trio
    async def test_resolve_self_upgrading_transport(self) -> None:
        """QUIC-like transport skips security + muxer."""
        reg = _build_registry(capable_transport=True)
        resolver = ConnectionResolver(reg)
        stack = await resolver.resolve(_quic_maddr(), _peer_id())

        assert stack.raw_conn is not None
        assert stack.skipped_security
        assert stack.skipped_muxer
        assert stack.secure_conn is None
        assert stack.muxed_conn is None

    @pytest.mark.trio
    async def test_resolve_security_only_transport(self) -> None:
        """Transport provides security but not muxing."""

        class _SecOnlyTransport:
            @property
            def provides_security(self) -> bool:
                return True

            @property
            def provides_muxing(self) -> bool:
                return False

            async def dial(self, maddr: object) -> _StubRawConn:
                return _StubRawConn()

        reg = ProviderRegistry()
        reg.register_transport(TransportProvider("tls-tcp", _SecOnlyTransport()))
        reg.register_muxer(MuxerProvider(TProtocol("/yamux/1.0.0"), _StubMuxerClass))

        resolver = ConnectionResolver(reg)
        maddr = _FakeMaddr(["ip4", "tls-tcp"])
        stack = await resolver.resolve(maddr, _peer_id())

        assert stack.skipped_security
        assert not stack.skipped_muxer
        assert stack.muxed_conn is not None


class TestResolverErrorPaths:
    """Tests for resolution failure modes."""

    @pytest.mark.trio
    async def test_no_transport_for_maddr(self) -> None:
        """No transport can dial the address."""
        reg = _build_registry(
            transport=_StubTransport(),
            transport_name="tcp",
        )
        resolver = ConnectionResolver(reg)
        quic_maddr = _quic_maddr()
        with pytest.raises(NoTransportError, match="No registered transport"):
            await resolver.resolve(quic_maddr, _peer_id())

    @pytest.mark.trio
    async def test_empty_registry_raises_no_transport(self) -> None:
        reg = ProviderRegistry()
        resolver = ConnectionResolver(reg)
        with pytest.raises(NoTransportError):
            await resolver.resolve(_tcp_maddr(), _peer_id())

    @pytest.mark.trio
    async def test_transport_dial_failure_all_paths_failed(self) -> None:
        """Transport dial fails → AllPathsFailedError."""
        reg = _build_registry(transport=_FailingTransport())
        resolver = ConnectionResolver(reg)
        with pytest.raises(AllPathsFailedError) as exc_info:
            await resolver.resolve(_tcp_maddr(), _peer_id())
        assert len(exc_info.value.failures) == 1

    @pytest.mark.trio
    async def test_security_upgrade_failure(self) -> None:
        """Security upgrade fails for all providers → AllPathsFailedError."""
        reg = _build_registry(
            transport=_StubTransport(),
            sec_transport=_FailingSecureTransport(),
            muxer_class=_StubMuxerClass,
        )
        resolver = ConnectionResolver(reg)
        with pytest.raises(AllPathsFailedError):
            await resolver.resolve(_tcp_maddr(), _peer_id())

    @pytest.mark.trio
    async def test_no_security_providers_registered(self) -> None:
        """No security providers → SecurityUpgradeFailure wrapped in AllPaths."""
        reg = _build_registry(
            transport=_StubTransport(),
            muxer_class=_StubMuxerClass,
        )
        resolver = ConnectionResolver(reg)
        with pytest.raises(AllPathsFailedError):
            await resolver.resolve(_tcp_maddr(), _peer_id())

    @pytest.mark.trio
    async def test_no_muxer_providers_registered(self) -> None:
        """No muxer providers → MuxerUpgradeFailure wrapped in AllPaths."""
        reg = _build_registry(
            transport=_StubTransport(),
            sec_transport=_StubSecureTransport(),
        )
        resolver = ConnectionResolver(reg)
        with pytest.raises(AllPathsFailedError):
            await resolver.resolve(_tcp_maddr(), _peer_id())


class TestResolverFallback:
    """Tests for multi-transport fallback behaviour."""

    @pytest.mark.trio
    async def test_fallback_to_second_transport(self) -> None:
        """First transport fails, second succeeds."""
        reg = ProviderRegistry()
        reg.register_transport(TransportProvider("tcp", _FailingTransport()))
        reg.register_transport(TransportProvider("tcp", _StubTransport()))
        reg.register_security(
            SecurityProvider(TProtocol("/noise"), _StubSecureTransport())
        )
        reg.register_muxer(MuxerProvider(TProtocol("/yamux/1.0.0"), _StubMuxerClass))

        resolver = ConnectionResolver(reg)
        stack = await resolver.resolve(_tcp_maddr(), _peer_id())

        assert stack.raw_conn is not None
        assert stack.muxed_conn is not None


class TestResolverInbound:
    """Tests for inbound (listener-accepted) connection upgrades."""

    @pytest.mark.trio
    async def test_inbound_full_upgrade(self) -> None:
        """Inbound: security + muxer applied."""
        reg = _build_registry(
            sec_transport=_StubSecureTransport(),
            muxer_class=_StubMuxerClass,
        )
        resolver = ConnectionResolver(reg)
        raw = _StubRawConn()
        stack = await resolver.upgrade_inbound(raw)

        assert stack.raw_conn is raw
        assert stack.secure_conn is not None
        assert stack.muxed_conn is not None
        assert not stack.skipped_security
        assert not stack.skipped_muxer

    @pytest.mark.trio
    async def test_inbound_self_upgrading_transport(self) -> None:
        """Inbound from a self-upgrading transport — skip both layers."""
        reg = ProviderRegistry()
        resolver = ConnectionResolver(reg)
        raw = _StubRawConn()
        stack = await resolver.upgrade_inbound(
            raw,
            transport_has_security=True,
            transport_has_muxing=True,
        )
        assert stack.skipped_security
        assert stack.skipped_muxer

    @pytest.mark.trio
    async def test_inbound_no_security_providers(self) -> None:
        """Inbound with no security providers → SecurityUpgradeFailure."""
        reg = ProviderRegistry()
        resolver = ConnectionResolver(reg)
        with pytest.raises(SecurityUpgradeFailure):
            await resolver.upgrade_inbound(_StubRawConn())

    @pytest.mark.trio
    async def test_inbound_no_muxer_providers(self) -> None:
        """Inbound with no muxer providers → MuxerUpgradeFailure."""
        reg = _build_registry(sec_transport=_StubSecureTransport())
        resolver = ConnectionResolver(reg)
        with pytest.raises(MuxerUpgradeFailure):
            await resolver.upgrade_inbound(_StubRawConn())

    @pytest.mark.trio
    async def test_inbound_security_skip_muxer_applied(self) -> None:
        """Inbound: transport has security, muxer still applied."""
        reg = _build_registry(muxer_class=_StubMuxerClass)
        resolver = ConnectionResolver(reg)
        raw = _StubRawConn()
        stack = await resolver.upgrade_inbound(
            raw,
            transport_has_security=True,
        )
        assert stack.skipped_security
        assert not stack.skipped_muxer
        assert stack.muxed_conn is not None
