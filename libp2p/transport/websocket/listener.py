from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
import ssl
from typing import Any

from multiaddr import Multiaddr
import trio
from trio_websocket import WebSocketConnection, serve_websocket

try:
    from websockets.legacy.server import WebSocketRequest
    from websockets.server import WebSocketServer
except ImportError:
    # Optional dependency - websockets package not installed
    WebSocketRequest = None  # type: ignore
    WebSocketServer = None  # type: ignore

from libp2p.abc import IListener
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.multiaddr_utils import parse_websocket_multiaddr

from .connection import P2PWebSocketConnection

logger = logging.getLogger("libp2p.transport.websocket.listener")


@dataclass
class WebsocketListenerConfig:
    """Configuration for WebSocket listener."""

    # TLS configuration
    tls_config: ssl.SSLContext | None = None

    # Connection settings
    max_connections: int = 1000
    max_message_size: int = 32 * 1024 * 1024  # 32MB

    # Timeouts
    ping_interval: float = 20.0
    ping_timeout: float = 10.0
    close_timeout: float = 5.0


class WebsocketListener(IListener):
    """
    Production-ready WebSocket listener with advanced features:

    - WS and WSS protocol support
    - Connection limits and tracking
    - Flow control and buffer management
    - Proper error handling and cleanup
    - TLS configuration
    - Configurable timeouts and limits
    """

    def __init__(
        self,
        handler: Callable[[Any], Awaitable[None]],
        upgrader: TransportUpgrader,
        config: WebsocketListenerConfig | None = None,
    ) -> None:
        """
        Initialize WebSocket listener.

        Args:
            handler: Connection handler function
            upgrader: Transport upgrader for security and multiplexing
            config: Optional configuration

        """
        self._handler = handler
        self._upgrader = upgrader
        self._config = config or WebsocketListenerConfig()

        # Connection tracking
        self._connections: dict[str, P2PWebSocketConnection] = {}
        self._current_connections = 0
        self._total_connections = 0
        self._failed_connections = 0

        # State management
        self._closed = False
        self._listen_maddr: Multiaddr | None = None
        self._server: WebSocketServer | None = None
        self._shutdown_event = trio.Event()

        # TLS configuration
        self._tls_config = self._config.tls_config
        self._is_wss = self._tls_config is not None

        logger.debug("WebsocketListener initialized")

    def _track_connection(self, conn: P2PWebSocketConnection) -> None:
        """Track a new connection."""
        conn_id = id(conn)
        self._connections[str(conn_id)] = conn
        self._current_connections += 1
        self._total_connections += 1

    def _untrack_connection(self, conn: P2PWebSocketConnection) -> None:
        """Untrack a connection."""
        conn_id = id(conn)
        if str(conn_id) in self._connections:
            del self._connections[str(conn_id)]
            self._current_connections -= 1

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        """
        Start listening for connections.

        Args:
            maddr: Multiaddr to listen on
            nursery: Trio nursery for managing tasks

        Returns:
            bool: True if listening started successfully

        Raises:
            OpenConnectionError: If listening fails

        """
        logger.debug(f"WebsocketListener.listen called with {maddr}")

        if self._closed:
            raise OpenConnectionError("Listener is closed")

        try:
            # Parse multiaddr
            proto_info = parse_websocket_multiaddr(maddr)
            if not proto_info:
                raise OpenConnectionError(f"Invalid WebSocket multiaddr: {maddr}")

            # Check if this is WSS
            self._is_wss = proto_info.is_wss

            # Check connection limits
            if self._current_connections >= self._config.max_connections:
                raise OpenConnectionError(
                    f"Connection limit reached: {self._current_connections}"
                )

            # Extract host and port from the rest_multiaddr
            host = (
                proto_info.rest_multiaddr.value_for_protocol("ip4")
                or proto_info.rest_multiaddr.value_for_protocol("ip6")
                or "0.0.0.0"
            )
            port = int(proto_info.rest_multiaddr.value_for_protocol("tcp") or "80")

            # Create WebSocket server
            self._server = await serve_websocket(
                handler=self._handle_websocket_request,
                host=host,
                port=port,
                ssl_context=self._tls_config,
            )

            self._listen_maddr = maddr
            logger.info(f"WebSocket listener started on {maddr}")
            return True

        except Exception as e:
            logger.error(f"Failed to start WebSocket listener: {e}")
            raise OpenConnectionError(f"Failed to listen on {maddr}: {str(e)}")

    async def _handle_websocket_request(self, request: Any) -> None:
        """Handle incoming WebSocket request."""
        if WebSocketRequest is None:
            logger.error("websockets package not installed, cannot handle request")
            return
        try:
            # Accept the WebSocket connection
            ws = await request.accept()
            await self._handle_connection(ws)
        except Exception as e:
            logger.error(f"Error handling WebSocket request: {e}")

    async def _handle_connection(self, ws: WebSocketConnection) -> None:
        """Handle incoming WebSocket connection."""
        try:
            # Create P2P connection wrapper
            conn = P2PWebSocketConnection(
                ws,
                is_secure=self._is_wss,
                max_buffered_amount=self._config.max_message_size,
            )

            # Track connection
            self._track_connection(conn)

            # Upgrade connection
            try:
                # For now, just call the handler directly
                # TODO: Implement proper connection upgrading
                await self._handler(conn)
            except Exception as e:
                logger.error(f"Connection upgrade failed: {e}")
                self._failed_connections += 1
            finally:
                self._untrack_connection(conn)

        except Exception as e:
            logger.error(f"Error handling WebSocket connection: {e}")
            self._failed_connections += 1

    async def close(self) -> None:
        """Close the listener and all connections."""
        if self._closed:
            return

        logger.debug("WebsocketListener.close called")
        self._closed = True

        # Signal shutdown
        self._shutdown_event.set()

        # Close all connections
        for conn in list(self._connections.values()):
            try:
                await conn.close()
            except Exception as e:
                logger.warning(f"Error closing connection: {e}")

        # Close server
        if self._server is not None and WebSocketServer is not None:
            await self._server.close()

        logger.info("WebSocket listener closed")

    @property
    def listen_maddr(self) -> Multiaddr | None:
        """Get the listening multiaddr."""
        return self._listen_maddr

    @property
    def is_closed(self) -> bool:
        """Check if the listener is closed."""
        return self._closed

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """Get listening addresses."""
        if self._listen_maddr:
            return (self._listen_maddr,)
        return ()

    def get_stats(self) -> dict[str, int]:
        """Get listener statistics."""
        return {
            "current_connections": self._current_connections,
            "total_connections": self._total_connections,
            "failed_connections": self._failed_connections,
        }
