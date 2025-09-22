"""
Tests for the transport registry functionality.
"""

from multiaddr import Multiaddr

from libp2p.abc import IListener, IRawConnection, ITransport
from libp2p.custom_types import THandler
from libp2p.transport.tcp.tcp import TCP
from libp2p.transport.transport_registry import (
    TransportRegistry,
    create_transport_for_multiaddr,
    get_supported_transport_protocols,
    get_transport_registry,
    register_transport,
)
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.transport import WebsocketTransport


class TestTransportRegistry:
    """Test the TransportRegistry class."""

    def test_init(self):
        """Test registry initialization."""
        registry = TransportRegistry()
        assert isinstance(registry, TransportRegistry)

        # Check that default transports are registered
        supported = registry.get_supported_protocols()
        assert "tcp" in supported
        assert "ws" in supported

    def test_register_transport(self):
        """Test transport registration."""
        registry = TransportRegistry()

        # Register a custom transport
        class CustomTransport(ITransport):
            async def dial(self, maddr: Multiaddr) -> IRawConnection:
                raise NotImplementedError("CustomTransport dial not implemented")

            def create_listener(self, handler_function: THandler) -> IListener:
                raise NotImplementedError(
                    "CustomTransport create_listener not implemented"
                )

        registry.register_transport("custom", CustomTransport)
        assert registry.get_transport("custom") == CustomTransport

    def test_get_transport(self):
        """Test getting registered transports."""
        registry = TransportRegistry()

        # Test existing transports
        assert registry.get_transport("tcp") == TCP
        assert registry.get_transport("ws") == WebsocketTransport

        # Test non-existent transport
        assert registry.get_transport("nonexistent") is None

    def test_get_supported_protocols(self):
        """Test getting supported protocols."""
        registry = TransportRegistry()
        protocols = registry.get_supported_protocols()

        assert isinstance(protocols, list)
        assert "tcp" in protocols
        assert "ws" in protocols

    def test_create_transport_tcp(self):
        """Test creating TCP transport."""
        registry = TransportRegistry()
        upgrader = TransportUpgrader({}, {})

        transport = registry.create_transport("tcp", upgrader)
        assert isinstance(transport, TCP)

    def test_create_transport_websocket(self):
        """Test creating WebSocket transport."""
        registry = TransportRegistry()
        upgrader = TransportUpgrader({}, {})

        transport = registry.create_transport("ws", upgrader)
        assert isinstance(transport, WebsocketTransport)

    def test_create_transport_invalid_protocol(self):
        """Test creating transport with invalid protocol."""
        registry = TransportRegistry()
        upgrader = TransportUpgrader({}, {})

        transport = registry.create_transport("invalid", upgrader)
        assert transport is None

    def test_create_transport_websocket_no_upgrader(self):
        """Test that WebSocket transport requires upgrader."""
        registry = TransportRegistry()

        # This should fail gracefully and return None
        transport = registry.create_transport("ws", None)
        assert transport is None


class TestGlobalRegistry:
    """Test the global registry functions."""

    def test_get_transport_registry(self):
        """Test getting the global registry."""
        registry = get_transport_registry()
        assert isinstance(registry, TransportRegistry)

    def test_register_transport_global(self):
        """Test registering transport globally."""

        class GlobalCustomTransport(ITransport):
            async def dial(self, maddr: Multiaddr) -> IRawConnection:
                raise NotImplementedError("GlobalCustomTransport dial not implemented")

            def create_listener(self, handler_function: THandler) -> IListener:
                raise NotImplementedError(
                    "GlobalCustomTransport create_listener not implemented"
                )

        # Register globally
        register_transport("global_custom", GlobalCustomTransport)

        # Check that it's available
        registry = get_transport_registry()
        assert registry.get_transport("global_custom") == GlobalCustomTransport

    def test_get_supported_transport_protocols_global(self):
        """Test getting supported protocols from global registry."""
        protocols = get_supported_transport_protocols()
        assert isinstance(protocols, list)
        assert "tcp" in protocols
        assert "ws" in protocols


class TestTransportFactory:
    """Test the transport factory functions."""

    def test_create_transport_for_multiaddr_tcp(self):
        """Test creating transport for TCP multiaddr."""
        upgrader = TransportUpgrader({}, {})

        # TCP multiaddr
        maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080")
        transport = create_transport_for_multiaddr(maddr, upgrader)

        assert transport is not None
        assert isinstance(transport, TCP)

    def test_create_transport_for_multiaddr_websocket(self):
        """Test creating transport for WebSocket multiaddr."""
        upgrader = TransportUpgrader({}, {})

        # WebSocket multiaddr
        maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")
        transport = create_transport_for_multiaddr(maddr, upgrader)

        assert transport is not None
        assert isinstance(transport, WebsocketTransport)

    def test_create_transport_for_multiaddr_websocket_secure(self):
        """Test creating transport for WebSocket multiaddr."""
        upgrader = TransportUpgrader({}, {})

        # WebSocket multiaddr
        maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")
        transport = create_transport_for_multiaddr(maddr, upgrader)

        assert transport is not None
        assert isinstance(transport, WebsocketTransport)

    def test_create_transport_for_multiaddr_ipv6(self):
        """Test creating transport for IPv6 multiaddr."""
        upgrader = TransportUpgrader({}, {})

        # IPv6 WebSocket multiaddr
        maddr = Multiaddr("/ip6/::1/tcp/8080/ws")
        transport = create_transport_for_multiaddr(maddr, upgrader)

        assert transport is not None
        assert isinstance(transport, WebsocketTransport)

    def test_create_transport_for_multiaddr_dns(self):
        """Test creating transport for DNS multiaddr."""
        upgrader = TransportUpgrader({}, {})

        # DNS WebSocket multiaddr
        maddr = Multiaddr("/dns4/example.com/tcp/443/ws")
        transport = create_transport_for_multiaddr(maddr, upgrader)

        assert transport is not None
        assert isinstance(transport, WebsocketTransport)

    def test_create_transport_for_multiaddr_unknown(self):
        """Test creating transport for unknown multiaddr."""
        upgrader = TransportUpgrader({}, {})

        # Unknown multiaddr
        maddr = Multiaddr("/ip4/127.0.0.1/udp/8080")
        transport = create_transport_for_multiaddr(maddr, upgrader)

        assert transport is None

    def test_create_transport_for_multiaddr_with_upgrader(self):
        """Test creating transport with upgrader."""
        upgrader = TransportUpgrader({}, {})

        # This should work for both TCP and WebSocket with upgrader
        maddr_tcp = Multiaddr("/ip4/127.0.0.1/tcp/8080")
        transport_tcp = create_transport_for_multiaddr(maddr_tcp, upgrader)
        assert transport_tcp is not None

        maddr_ws = Multiaddr("/ip4/127.0.0.1/tcp/8080/ws")
        transport_ws = create_transport_for_multiaddr(maddr_ws, upgrader)
        assert transport_ws is not None


class TestTransportInterfaceCompliance:
    """Test that all transports implement the required interface."""

    def test_tcp_implements_itransport(self):
        """Test that TCP transport implements ITransport."""
        transport = TCP()
        assert isinstance(transport, ITransport)
        assert hasattr(transport, "dial")
        assert hasattr(transport, "create_listener")
        assert callable(transport.dial)
        assert callable(transport.create_listener)

    def test_websocket_implements_itransport(self):
        """Test that WebSocket transport implements ITransport."""
        upgrader = TransportUpgrader({}, {})
        transport = WebsocketTransport(upgrader)
        assert isinstance(transport, ITransport)
        assert hasattr(transport, "dial")
        assert hasattr(transport, "create_listener")
        assert callable(transport.dial)
        assert callable(transport.create_listener)


class TestErrorHandling:
    """Test error handling in the transport registry."""

    def test_create_transport_with_exception(self):
        """Test handling of transport creation exceptions."""
        registry = TransportRegistry()
        upgrader = TransportUpgrader({}, {})

        # Register a transport that raises an exception
        class ExceptionTransport(ITransport):
            def __init__(self, *args, **kwargs):
                raise RuntimeError("Transport creation failed")

            async def dial(self, maddr: Multiaddr) -> IRawConnection:
                raise NotImplementedError("ExceptionTransport dial not implemented")

            def create_listener(self, handler_function: THandler) -> IListener:
                raise NotImplementedError(
                    "ExceptionTransport create_listener not implemented"
                )

        registry.register_transport("exception", ExceptionTransport)

        # Should handle exception gracefully and return None
        transport = registry.create_transport("exception", upgrader)
        assert transport is None

    def test_invalid_multiaddr_handling(self):
        """Test handling of invalid multiaddrs."""
        upgrader = TransportUpgrader({}, {})

        # Test with a multiaddr that has an unsupported transport protocol
        # This should be handled gracefully by our transport registry
        # udp is not a supported transport
        maddr = Multiaddr("/ip4/127.0.0.1/tcp/8080/udp/1234")
        transport = create_transport_for_multiaddr(maddr, upgrader)

        assert transport is None


class TestIntegration:
    """Test integration scenarios."""

    def test_multiple_transport_types(self):
        """Test using multiple transport types in the same registry."""
        registry = TransportRegistry()
        upgrader = TransportUpgrader({}, {})

        # Create different transport types
        tcp_transport = registry.create_transport("tcp", upgrader)
        ws_transport = registry.create_transport("ws", upgrader)

        # All should be different types
        assert isinstance(tcp_transport, TCP)
        assert isinstance(ws_transport, WebsocketTransport)

        # All should be different instances
        assert tcp_transport is not ws_transport

    def test_transport_registry_persistence(self):
        """Test that transport registry persists across calls."""
        registry1 = get_transport_registry()
        registry2 = get_transport_registry()

        # Should be the same instance
        assert registry1 is registry2

        # Register a transport in one
        class PersistentTransport(ITransport):
            async def dial(self, maddr: Multiaddr) -> IRawConnection:
                raise NotImplementedError("PersistentTransport dial not implemented")

            def create_listener(self, handler_function: THandler) -> IListener:
                raise NotImplementedError(
                    "PersistentTransport create_listener not implemented"
                )

        registry1.register_transport("persistent", PersistentTransport)

        # Should be available in the other
        assert registry2.get_transport("persistent") == PersistentTransport
