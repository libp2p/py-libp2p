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
from .manager import TransportManager
from .upgrader import TransportUpgrader
from .cmux import PortDemultiplexer, DemultiplexedConnType, DemultiplexedListener, identify_conn_type
from libp2p.abc import ITransport


def create_transport(
    protocol: str, upgrader: TransportUpgrader | None = None, **kwargs: Any
) -> ITransport:
    """
    Convenience function to create a transport instance.

    :param protocol: The transport protocol (``"tcp"``, ``"ws"``, ``"wss"``,
        or a custom registered protocol).
    :param upgrader: Optional transport upgrader (required for WebSocket).
    :param kwargs: Additional arguments for transport construction
        (e.g. ``tls_client_config``, ``tls_server_config``).
    :return: Transport instance.
    """
    if protocol in ["ws", "wss"]:
        if upgrader is None:
            raise ValueError("WebSocket transport requires an upgrader")
        from libp2p.transport.websocket.transport import WebsocketConfig, WebsocketTransport

        config = WebsocketConfig(
            tls_client_config=kwargs.get("tls_client_config"),
            tls_server_config=kwargs.get("tls_server_config"),
            handshake_timeout=kwargs.get("handshake_timeout", 15.0),
        )
        return WebsocketTransport(upgrader, config)
    elif protocol == "tcp":
        return TCP()
    else:
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
    # Transports
    "TCP",
    "TransportManager",
    "WebsocketTransport",
    # Registry helpers
    "TransportRegistry",
    "create_transport_for_multiaddr",
    "create_transport",
    "get_transport_registry",
    "register_transport",
    "get_supported_transport_protocols",
    # Port sharing / cmux
    "PortDemultiplexer",
    "DemultiplexedConnType",
    "DemultiplexedListener",
    "identify_conn_type",
]
