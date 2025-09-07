"""
Transport registry for dynamic transport selection based on multiaddr protocols.
"""

import logging
from typing import Any

from multiaddr import Multiaddr
from multiaddr.protocols import Protocol

from libp2p.abc import ITransport
from libp2p.transport.tcp.tcp import TCP
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.multiaddr_utils import (
    is_valid_websocket_multiaddr,
)


# Import WebsocketTransport here to avoid circular imports
def _get_websocket_transport():
    from libp2p.transport.websocket.transport import WebsocketTransport

    return WebsocketTransport


logger = logging.getLogger("libp2p.transport.registry")


def _is_valid_tcp_multiaddr(maddr: Multiaddr) -> bool:
    """
    Validate that a multiaddr has a valid TCP structure.

    :param maddr: The multiaddr to validate
    :return: True if valid TCP structure, False otherwise
    """
    try:
        # TCP multiaddr should have structure like /ip4/127.0.0.1/tcp/8080
        # or /ip6/::1/tcp/8080
        protocols: list[Protocol] = list(maddr.protocols())

        # Must have at least 2 protocols: network (ip4/ip6) + tcp
        if len(protocols) < 2:
            return False

        # First protocol should be a network protocol (ip4, ip6, dns4, dns6)
        if protocols[0].name not in ["ip4", "ip6", "dns4", "dns6"]:
            return False

        # Second protocol should be tcp
        if protocols[1].name != "tcp":
            return False

        # Should not have any protocols after tcp (unless it's a valid
        # continuation like p2p)
        # For now, we'll be strict and only allow network + tcp
        if len(protocols) > 2:
            # Check if the additional protocols are valid continuations
            valid_continuations = ["p2p"]  # Add more as needed
            for i in range(2, len(protocols)):
                if protocols[i].name not in valid_continuations:
                    return False

        return True

    except Exception:
        return False


class TransportRegistry:
    """
    Registry for mapping multiaddr protocols to transport implementations.
    """

    def __init__(self) -> None:
        self._transports: dict[str, type[ITransport]] = {}
        self._register_default_transports()

    def _register_default_transports(self) -> None:
        """Register the default transport implementations."""
        # Register TCP transport for /tcp protocol
        self.register_transport("tcp", TCP)

        # Register WebSocket transport for /ws and /wss protocols
        WebsocketTransport = _get_websocket_transport()
        self.register_transport("ws", WebsocketTransport)
        self.register_transport("wss", WebsocketTransport)

    def register_transport(
        self, protocol: str, transport_class: type[ITransport]
    ) -> None:
        """
        Register a transport class for a specific protocol.

        :param protocol: The protocol identifier (e.g., "tcp", "ws")
        :param transport_class: The transport class to register
        """
        self._transports[protocol] = transport_class
        logger.debug(
            f"Registered transport {transport_class.__name__} for protocol {protocol}"
        )

    def get_transport(self, protocol: str) -> type[ITransport] | None:
        """
        Get the transport class for a specific protocol.

        :param protocol: The protocol identifier
        :return: The transport class or None if not found
        """
        return self._transports.get(protocol)

    def get_supported_protocols(self) -> list[str]:
        """Get list of supported transport protocols."""
        return list(self._transports.keys())

    def create_transport(
        self, protocol: str, upgrader: TransportUpgrader | None = None, **kwargs: Any
    ) -> ITransport | None:
        """
        Create a transport instance for a specific protocol.

        :param protocol: The protocol identifier
        :param upgrader: The transport upgrader instance (required for WebSocket)
        :param kwargs: Additional arguments for transport construction
        :return: Transport instance or None if protocol not supported or creation fails
        """
        transport_class = self.get_transport(protocol)
        if transport_class is None:
            return None

        try:
            if protocol in ["ws", "wss"]:
                # WebSocket transport requires upgrader
                if upgrader is None:
                    logger.warning(
                        f"WebSocket transport '{protocol}' requires upgrader"
                    )
                    return None
                # Use explicit WebsocketTransport to avoid type issues
                WebsocketTransport = _get_websocket_transport()
                return WebsocketTransport(upgrader)
            else:
                # TCP transport doesn't require upgrader
                return transport_class()
        except Exception as e:
            logger.error(f"Failed to create transport for protocol {protocol}: {e}")
            return None


# Global transport registry instance
_global_registry = TransportRegistry()


def get_transport_registry() -> TransportRegistry:
    """Get the global transport registry instance."""
    return _global_registry


def register_transport(protocol: str, transport_class: type[ITransport]) -> None:
    """Register a transport class in the global registry."""
    _global_registry.register_transport(protocol, transport_class)


def create_transport_for_multiaddr(
    maddr: Multiaddr, upgrader: TransportUpgrader
) -> ITransport | None:
    """
    Create the appropriate transport for a given multiaddr.

    :param maddr: The multiaddr to create transport for
    :param upgrader: The transport upgrader instance
    :return: Transport instance or None if no suitable transport found
    """
    try:
        # Get all protocols in the multiaddr
        protocols = [proto.name for proto in maddr.protocols()]

        # Check for supported transport protocols in order of preference
        # We need to validate that the multiaddr structure is valid for our transports
        if "ws" in protocols or "wss" in protocols or "tls" in protocols:
            # For WebSocket, we need a valid structure like:
            # /ip4/127.0.0.1/tcp/8080/ws (insecure)
            # /ip4/127.0.0.1/tcp/8080/wss (secure)
            # /ip4/127.0.0.1/tcp/8080/tls/ws (secure with TLS)
            # /ip4/127.0.0.1/tcp/8080/tls/sni/example.com/ws (secure with SNI)
            if is_valid_websocket_multiaddr(maddr):
                # Determine if this is a secure WebSocket connection
                if "wss" in protocols or "tls" in protocols:
                    return _global_registry.create_transport("wss", upgrader)
                else:
                    return _global_registry.create_transport("ws", upgrader)
        elif "tcp" in protocols:
            # For TCP, we need a valid structure like /ip4/127.0.0.1/tcp/8080
            # Check if the multiaddr has proper TCP structure
            if _is_valid_tcp_multiaddr(maddr):
                return _global_registry.create_transport("tcp", upgrader)

        # If no supported transport protocol found or structure is invalid, return None
        logger.warning(
            f"No supported transport protocol found or invalid structure in "
            f"multiaddr: {maddr}"
        )
        return None

    except Exception as e:
        # Handle any errors gracefully (e.g., invalid multiaddr)
        logger.warning(f"Error processing multiaddr {maddr}: {e}")
        return None


def get_supported_transport_protocols() -> list[str]:
    """Get list of supported transport protocols from the global registry."""
    return _global_registry.get_supported_protocols()
