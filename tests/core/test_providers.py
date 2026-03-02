"""
Tests for the provider abstractions.

Validates:
- ``ProvidesTransport`` / ``ProvidesConnection`` structural protocols
- ``SecurityProvider``, ``MuxerProvider``, ``TransportProvider`` wrappers
- ``ProviderRegistry`` registration, bulk-import, and query methods
"""

from __future__ import annotations

from collections import OrderedDict

import pytest

from libp2p.abc import (
    IMuxedConn,
    IRawConnection,
    ISecureConn,
)
from libp2p.custom_types import TMuxerOptions, TProtocol, TSecurityOptions
from libp2p.peer.id import ID
from libp2p.providers import (
    MuxerProvider,
    ProviderRegistry,
    ProvidesConnection,
    ProvidesTransport,
    SecurityProvider,
    TransportProvider,
)


class _StubRawConn:
    """Minimal stub implementing enough for SecurityProvider.upgrade."""

    async def close(self) -> None:
        pass


class _StubSecureConn:
    """Minimal stub for ISecureConn-like objects."""

    def get_remote_peer(self) -> ID:
        return ID(b"\x01\x02")

    async def close(self) -> None:
        pass


class _StubMuxedConn:
    """Minimal stub for IMuxedConn-like objects."""

    pass


class _StubSecureTransport:
    """Minimal stub implementing ISecureTransport's relevant methods."""

    async def secure_outbound(self, conn: object, peer_id: ID) -> _StubSecureConn:
        return _StubSecureConn()

    async def secure_inbound(self, conn: object) -> _StubSecureConn:
        return _StubSecureConn()


class _StubMuxerClass:
    """Callable stub that simulates a muxer constructor."""

    def __init__(self, conn: object, peer_id: ID) -> None:
        self.conn = conn
        self.peer_id = peer_id


class _StubTransport:
    """Minimal ITransport-like stub."""

    async def dial(self, maddr: object) -> _StubRawConn:
        return _StubRawConn()

    async def create_listener(self, handler: object) -> None:
        pass


class _CapableTransport(_StubTransport):
    """Transport that provides security + muxing (like QUIC)."""

    @property
    def provides_security(self) -> bool:
        return True

    @property
    def provides_muxing(self) -> bool:
        return True


class _ConformingProvider:
    """A class that structurally conforms to ProvidesTransport."""

    def can_dial(self, maddr: object) -> bool:
        return True

    async def dial(self, maddr: object) -> IRawConnection: ...


class _NonConformingObject:
    """Object that does NOT conform to ProvidesTransport."""

    pass


class _ConnectionLayerConforming:
    """Conforms to ProvidesConnection."""

    @property
    def provides_interface(self) -> type:
        return ISecureConn

    @property
    def requires_interface(self) -> type:
        return IRawConnection


class _ProtoStub:
    """Simple object with a .name attribute."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeMaddr:
    """Fake multiaddr for testing transport matching."""

    def __init__(self, proto_names: list[str]) -> None:
        self._proto_names = proto_names

    def protocols(self) -> list[_ProtoStub]:
        return [_ProtoStub(n) for n in self._proto_names]


class TestProvidesTransportProtocol:
    """Tests for the ProvidesTransport structural protocol."""

    def test_conforming_class_is_instance(self) -> None:
        assert isinstance(_ConformingProvider(), ProvidesTransport)

    def test_transport_provider_is_instance(self) -> None:
        tp = TransportProvider("tcp", _StubTransport())
        assert isinstance(tp, ProvidesTransport)

    def test_non_conforming_not_instance(self) -> None:
        assert not isinstance(_NonConformingObject(), ProvidesTransport)

    def test_plain_object_not_instance(self) -> None:
        assert not isinstance(42, ProvidesTransport)


class TestProvidesConnectionProtocol:
    """Tests for the ProvidesConnection structural protocol."""

    def test_conforming_class_is_instance(self) -> None:
        assert isinstance(_ConnectionLayerConforming(), ProvidesConnection)

    def test_security_provider_is_instance(self) -> None:
        sp = SecurityProvider(TProtocol("/noise"), _StubSecureTransport())
        assert isinstance(sp, ProvidesConnection)

    def test_muxer_provider_is_instance(self) -> None:
        mp = MuxerProvider(TProtocol("/yamux/1.0.0"), _StubMuxerClass)
        assert isinstance(mp, ProvidesConnection)

    def test_non_conforming_not_instance(self) -> None:
        assert not isinstance(_NonConformingObject(), ProvidesConnection)


class TestSecurityProvider:
    """Tests for the SecurityProvider wrapper."""

    def test_provides_and_requires_interfaces(self) -> None:
        sp = SecurityProvider(TProtocol("/noise"), _StubSecureTransport())
        assert sp.provides_interface is ISecureConn
        assert sp.requires_interface is IRawConnection

    @pytest.mark.trio
    async def test_upgrade_outbound(self) -> None:
        sp = SecurityProvider(TProtocol("/noise"), _StubSecureTransport())
        result = await sp.upgrade(
            _StubRawConn(), is_initiator=True, peer_id=ID(b"\x01")
        )
        assert isinstance(result, _StubSecureConn)

    @pytest.mark.trio
    async def test_upgrade_inbound(self) -> None:
        sp = SecurityProvider(TProtocol("/noise"), _StubSecureTransport())
        result = await sp.upgrade(_StubRawConn(), is_initiator=False)
        assert isinstance(result, _StubSecureConn)

    @pytest.mark.trio
    async def test_upgrade_outbound_requires_peer_id(self) -> None:
        sp = SecurityProvider(TProtocol("/noise"), _StubSecureTransport())
        with pytest.raises(ValueError, match="peer_id required"):
            await sp.upgrade(_StubRawConn(), is_initiator=True)

    def test_repr(self) -> None:
        sp = SecurityProvider(TProtocol("/noise"), _StubSecureTransport())
        assert "/noise" in repr(sp)


class TestMuxerProvider:
    """Tests for the MuxerProvider wrapper."""

    def test_provides_and_requires_interfaces(self) -> None:
        mp = MuxerProvider(TProtocol("/yamux/1.0.0"), _StubMuxerClass)
        assert mp.provides_interface is IMuxedConn
        assert mp.requires_interface is ISecureConn

    @pytest.mark.trio
    async def test_upgrade(self) -> None:
        mp = MuxerProvider(TProtocol("/yamux/1.0.0"), _StubMuxerClass)
        result = await mp.upgrade(_StubSecureConn(), ID(b"\x01"))
        assert isinstance(result, _StubMuxerClass)
        assert result.peer_id == ID(b"\x01")

    def test_repr(self) -> None:
        mp = MuxerProvider(TProtocol("/yamux/1.0.0"), _StubMuxerClass)
        assert "/yamux/1.0.0" in repr(mp)


class TestTransportProvider:
    """Tests for the TransportProvider wrapper."""

    def test_can_dial_with_protocol_name_match(self) -> None:
        tp = TransportProvider("tcp", _StubTransport())
        maddr = _FakeMaddr(["ip4", "tcp"])
        assert tp.can_dial(maddr)

    def test_can_dial_no_match(self) -> None:
        tp = TransportProvider("tcp", _StubTransport())
        maddr = _FakeMaddr(["ip4", "udp", "quic"])
        assert not tp.can_dial(maddr)

    def test_can_dial_with_custom_matcher(self) -> None:
        tp = TransportProvider("custom", _StubTransport(), matcher=lambda _: True)
        assert tp.can_dial(object())

    def test_can_dial_custom_matcher_false(self) -> None:
        tp = TransportProvider("custom", _StubTransport(), matcher=lambda _: False)
        assert not tp.can_dial(object())

    @pytest.mark.trio
    async def test_dial(self) -> None:
        tp = TransportProvider("tcp", _StubTransport())
        result = await tp.dial(object())
        assert isinstance(result, _StubRawConn)

    def test_provides_security_false_by_default(self) -> None:
        tp = TransportProvider("tcp", _StubTransport())
        assert not tp.provides_security

    def test_provides_muxing_false_by_default(self) -> None:
        tp = TransportProvider("tcp", _StubTransport())
        assert not tp.provides_muxing

    def test_provides_security_from_transport(self) -> None:
        tp = TransportProvider("quic", _CapableTransport())
        assert tp.provides_security

    def test_provides_muxing_from_transport(self) -> None:
        tp = TransportProvider("quic", _CapableTransport())
        assert tp.provides_muxing

    def test_repr(self) -> None:
        tp = TransportProvider("tcp", _StubTransport())
        assert "tcp" in repr(tp)


class TestProviderRegistry:
    """Tests for the ProviderRegistry."""

    def test_empty_registry(self) -> None:
        reg = ProviderRegistry()
        assert reg.get_transports() == []
        assert reg.get_security_providers() == []
        assert reg.get_muxer_providers() == []
        assert not reg.has_security()
        assert not reg.has_muxer()

    def test_register_transport(self) -> None:
        reg = ProviderRegistry()
        tp = TransportProvider("tcp", _StubTransport())
        reg.register_transport(tp)
        assert len(reg.get_transports()) == 1
        assert reg.get_transports()[0] is tp

    def test_register_security(self) -> None:
        reg = ProviderRegistry()
        sp = SecurityProvider(TProtocol("/noise"), _StubSecureTransport())
        reg.register_security(sp)
        assert len(reg.get_security_providers()) == 1
        assert reg.has_security()

    def test_register_muxer(self) -> None:
        reg = ProviderRegistry()
        mp = MuxerProvider(TProtocol("/yamux/1.0.0"), _StubMuxerClass)
        reg.register_muxer(mp)
        assert len(reg.get_muxer_providers()) == 1
        assert reg.has_muxer()

    def test_get_transports_for_matching(self) -> None:
        reg = ProviderRegistry()
        tcp_tp = TransportProvider("tcp", _StubTransport())
        quic_tp = TransportProvider("quic", _CapableTransport())
        reg.register_transport(tcp_tp)
        reg.register_transport(quic_tp)

        tcp_maddr = _FakeMaddr(["ip4", "tcp"])
        matches = reg.get_transports_for(tcp_maddr)
        assert len(matches) == 1
        assert matches[0] is tcp_tp

    def test_get_transports_for_no_match(self) -> None:
        reg = ProviderRegistry()
        tcp_tp = TransportProvider("tcp", _StubTransport())
        reg.register_transport(tcp_tp)

        quic_maddr = _FakeMaddr(["ip4", "udp", "quic"])
        assert reg.get_transports_for(quic_maddr) == []

    def test_register_security_options_bulk(self) -> None:
        reg = ProviderRegistry()
        sec_opts: TSecurityOptions = OrderedDict(
            {
                TProtocol("/noise"): _StubSecureTransport(),
                TProtocol("/tls/1.0.0"): _StubSecureTransport(),
            }
        )
        reg.register_security_options(sec_opts)
        assert len(reg.get_security_providers()) == 2
        assert reg.get_security_providers()[0].protocol_id == TProtocol("/noise")
        assert reg.get_security_providers()[1].protocol_id == TProtocol("/tls/1.0.0")

    def test_register_muxer_options_bulk(self) -> None:
        reg = ProviderRegistry()
        mux_opts: TMuxerOptions = OrderedDict(
            {
                TProtocol("/yamux/1.0.0"): _StubMuxerClass,
                TProtocol("/mplex/6.7.0"): _StubMuxerClass,
            }
        )
        reg.register_muxer_options(mux_opts)
        assert len(reg.get_muxer_providers()) == 2
        assert reg.get_muxer_providers()[0].protocol_id == TProtocol("/yamux/1.0.0")

    def test_repr(self) -> None:
        reg = ProviderRegistry()
        reg.register_transport(TransportProvider("tcp", _StubTransport()))
        reg.register_security(
            SecurityProvider(TProtocol("/noise"), _StubSecureTransport())
        )
        r = repr(reg)
        assert "transports=1" in r
        assert "security=1" in r
        assert "muxers=0" in r

    def test_multiple_transports_same_protocol(self) -> None:
        """Registering multiple transports with the same name is allowed."""
        reg = ProviderRegistry()
        tp1 = TransportProvider("tcp", _StubTransport())
        tp2 = TransportProvider("tcp", _StubTransport())
        reg.register_transport(tp1)
        reg.register_transport(tp2)
        assert len(reg.get_transports()) == 2
