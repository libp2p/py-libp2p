from .tcp.tcp import TCP
from .websocket.transport import WebsocketTransport
from .transport_registry import (
    TransportRegistry,
    create_transport_for_multiaddr,
    get_transport_registry,
    register_transport,
    get_supported_transport_protocols,
)
from .upgrader import TransportUpgrader
from libp2p.abc import ITransport

def create_transport(protocol: str, upgrader: TransportUpgrader | None = None) -> ITransport:
    """
    Convenience function to create a transport instance.

    :param protocol: The transport protocol ("tcp", "ws", or custom)
    :param upgrader: Optional transport upgrader (required for WebSocket)
    :return: Transport instance
    """
    # First check if it's a built-in protocol
    if protocol == "ws":
        if upgrader is None:
            raise ValueError(f"WebSocket transport requires an upgrader")
        return WebsocketTransport(upgrader)
    elif protocol == "tcp":
        return TCP()
    else:
        # Check if it's a custom registered transport
        registry = get_transport_registry()
        transport_class = registry.get_transport(protocol)
        if transport_class:
            transport = registry.create_transport(protocol, upgrader)
            if transport is None:
                raise ValueError(f"Failed to create transport for protocol: {protocol}")
            return transport
        else:
            raise ValueError(f"Unsupported transport protocol: {protocol}")

__all__ = [
    "TCP",
    "WebsocketTransport",
    "TransportRegistry",
    "create_transport_for_multiaddr",
    "create_transport",
    "get_transport_registry",
    "register_transport",
    "get_supported_transport_protocols",
]
