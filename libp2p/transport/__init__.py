from typing import Any

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

def create_transport(protocol: str, upgrader: TransportUpgrader | None = None, **kwargs: Any) -> ITransport:
    """
    Convenience function to create a transport instance.

    :param protocol: The transport protocol ("tcp", "ws", "wss", or custom)
    :param upgrader: Optional transport upgrader (required for WebSocket)
    :param kwargs: Additional arguments for transport construction (e.g., tls_client_config, tls_server_config)
    :return: Transport instance
    """
    # First check if it's a built-in protocol
    if protocol in ["ws", "wss"]:
        if upgrader is None:
            raise ValueError(f"WebSocket transport requires an upgrader")
        return WebsocketTransport(
            upgrader,
            tls_client_config=kwargs.get("tls_client_config"),
            tls_server_config=kwargs.get("tls_server_config"),
            handshake_timeout=kwargs.get("handshake_timeout", 15.0)
        )
    elif protocol == "tcp":
        return TCP()
    else:
        # Check if it's a custom registered transport
        registry = get_transport_registry()
        transport_class = registry.get_transport(protocol)
        if transport_class:
            transport = registry.create_transport(protocol, upgrader, **kwargs)
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
