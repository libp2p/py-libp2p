from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
import ssl
from typing import Any

from multiaddr import Multiaddr
import trio
from trio_typing import TaskStatus
from trio_websocket import WebSocketConnection, serve_websocket

try:
    from websockets.legacy.server import WebSocketRequest  # type: ignore
    from websockets.server import WebSocketServer  # type: ignore
except ImportError:
    # Optional dependency - websockets package not installed
    WebSocketRequest = None  # type: ignore
    WebSocketServer = None  # type: ignore

from libp2p.abc import IListener
from libp2p.peer.id import ID
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.multiaddr_utils import parse_websocket_multiaddr
from libp2p.utils.multiaddr_utils import extract_ip_from_multiaddr

from .autotls import AutoTLSConfig, AutoTLSManager
from .connection import P2PWebSocketConnection
from .tls_config import WebSocketTLSConfig

logger = logging.getLogger(__name__)


@dataclass
class WebsocketListenerConfig:
    """Configuration for WebSocket listener."""

    # TLS configuration
    tls_config: ssl.SSLContext | None = None

    # AutoTLS configuration
    autotls_config: AutoTLSConfig | None = None

    # Advanced TLS configuration
    advanced_tls_config: WebSocketTLSConfig | None = None

    # Connection settings
    max_connections: int = 1000
    max_message_size: int = 32 * 1024 * 1024  # 32MB

    # Timeouts
    handshake_timeout: float = 15.0
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
        peer_id: ID | None = None,
    ) -> None:
        """
        Initialize WebSocket listener.

        Args:
            handler: Connection handler function
            upgrader: Transport upgrader for security and multiplexing
            config: Optional configuration
            peer_id: Optional peer ID of the host

        """
        self._handler = handler
        self._upgrader = upgrader
        self._config = config or WebsocketListenerConfig()
        self._peer_id = peer_id

        # Configuration attributes for test access
        self._handshake_timeout = self._config.handshake_timeout

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

        # AutoTLS support
        self._autotls_manager: AutoTLSManager | None = None
        self._autotls_initialized = False

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

    async def _initialize_autotls(self, peer_id: ID | None = None) -> None:
        """Initialize AutoTLS if configured."""
        if self._autotls_initialized:
            return

        if self._config.autotls_config and self._config.autotls_config.enabled:
            try:
                from .autotls import initialize_autotls

                self._autotls_manager = await initialize_autotls(
                    self._config.autotls_config
                )
                logger.info(f"AutoTLS initialized for listener with peer {peer_id}")
                self._autotls_initialized = True
            except Exception as e:
                logger.error(f"Failed to initialize AutoTLS: {e}")
                raise

    async def _get_ssl_context(
        self,
        peer_id: ID | None = None,
        sni_name: str | None = None,
    ) -> ssl.SSLContext | None:
        """Get SSL context for connection."""
        # Check AutoTLS first
        if self._autotls_manager and peer_id:
            domain = sni_name or (
                self._config.autotls_config.default_domain
                if self._config.autotls_config
                else "libp2p.local"
            )
            context = self._autotls_manager.get_ssl_context(peer_id, domain)
            if context:
                return context

        # Check advanced TLS configuration
        if self._config.advanced_tls_config:
            return self._config.advanced_tls_config.get_ssl_context(peer_id, sni_name)

        # Fall back to legacy TLS configuration
        return self._tls_config

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        """
        Start listening for connections.

        Args:
            maddr: Multiaddr to listen on
            nursery: Trio nursery for managing tasks

        Returns:
            bool: True if listening started successfully

        :raises OpenConnectionError: If listening fails, listener is closed,
            invalid WebSocket multiaddr, or connection limit reached
        :raises ValueError: If WSS (secure WebSocket) requires TLS configuration
            but none was provided

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

            # Initialize AutoTLS if configured
            # This ensures certificates are ready before we start listening
            if self._config.autotls_config and self._config.autotls_config.enabled:
                await self._initialize_autotls(self._peer_id)

            # Validate TLS configuration for WSS
            if self._is_wss and self._tls_config is None:
                # If AutoTLS is enabled, we might have a context now
                if self._autotls_manager:
                    # AutoTLS will provide context per connection via SNI
                    pass
                else:
                    raise ValueError(
                        "WSS (secure WebSocket) requires TLS configuration but none "
                        "was provided. Please provide tls_server_config when creating "
                        "the WebSocket transport."
                    )

            # Check connection limits
            if self._current_connections >= self._config.max_connections:
                raise OpenConnectionError(
                    f"Connection limit reached: {self._current_connections}"
                )

            # Extract host and port from the rest_multiaddr
            host = extract_ip_from_multiaddr(proto_info.rest_multiaddr) or "0.0.0.0"
            port = int(proto_info.rest_multiaddr.value_for_protocol("tcp") or "80")

            # Create WebSocket server using nursery.start pattern
            server_info = None

            async def websocket_server_task(task_status: TaskStatus[Any]) -> None:
                """Run the WebSocket server."""
                nonlocal server_info
                try:
                    # Use trio_websocket's serve_websocket

                    # Create the server
                    await serve_websocket(
                        handler=self._handle_websocket_connection,
                        host=host,
                        port=port,
                        ssl_context=self._tls_config
                        or (
                            self._autotls_manager.get_ssl_context(
                                self._peer_id, "libp2p.local"
                            )
                            if self._autotls_manager
                            else None
                        ),
                        task_status=task_status,
                    )
                except Exception as e:
                    logger.error(f"WebSocket server error: {e}")
                    raise

            # Start the server in the nursery and capture the server info
            server_info = await nursery.start(websocket_server_task)

            # Store the server for later cleanup
            self._server = server_info

            # Extract the actual listening address and port from the server socket
            # This ensures we get the real bound address, especially for port 0 or DNS
            actual_host = host
            actual_port = port
            if server_info is not None:
                # Try to get actual bound address from socket
                if hasattr(server_info, "socket"):
                    sock = server_info.socket
                    if hasattr(sock, "getsockname"):
                        sock_addr, sock_port = sock.getsockname()
                        actual_host = sock_addr
                        actual_port = sock_port
                elif hasattr(server_info, "port"):
                    # If we can't get socket, at least get the port
                    actual_port = server_info.port
                elif port == 0:
                    # Port was 0 but we can't determine actual port
                    logger.warning("Could not determine actual port, using original")
                    actual_port = port

            # Create new multiaddr with actual port
            if proto_info.is_wss:
                protocol_part = "/wss"
            else:
                protocol_part = "/ws"

            # Determine IP version from actual bound address
            # Use IPv4 or IPv6 based on actual socket address, not original multiaddr
            try:
                # Check if actual_host is an IPv6 address
                if ":" in actual_host:
                    self._listen_maddr = Multiaddr(
                        f"/ip6/{actual_host}/tcp/{actual_port}{protocol_part}"
                    )
                else:
                    # IPv4 address
                    self._listen_maddr = Multiaddr(
                        f"/ip4/{actual_host}/tcp/{actual_port}{protocol_part}"
                    )
            except Exception as e:
                # Fallback: use original multiaddr structure if socket info unavailable
                logger.warning(f"Could not create listen address from socket: {e}")
                if "ip4" in str(proto_info.rest_multiaddr):
                    self._listen_maddr = Multiaddr(
                        f"/ip4/{actual_host}/tcp/{actual_port}{protocol_part}"
                    )
                elif "ip6" in str(proto_info.rest_multiaddr):
                    self._listen_maddr = Multiaddr(
                        f"/ip6/{actual_host}/tcp/{actual_port}{protocol_part}"
                    )
                else:
                    # Default to IPv4
                    self._listen_maddr = Multiaddr(
                        f"/ip4/{actual_host}/tcp/{actual_port}{protocol_part}"
                    )

            logger.info(f"WebSocket listener started on {self._listen_maddr}")
            return True

        except Exception as e:
            logger.error(f"Failed to start WebSocket listener: {e}")
            raise OpenConnectionError(f"Failed to listen on {maddr}: {str(e)}")

    async def _handle_websocket_connection(self, request: Any) -> None:
        """Handle incoming WebSocket connection from trio_websocket."""
        try:
            # trio_websocket provides the connection directly
            ws = request if hasattr(request, "send_message") else await request.accept()
            await self._handle_connection(ws)
        except Exception as e:
            logger.error(f"Error handling WebSocket connection: {e}")

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

            # Pass connection directly to handler
            # The handler (Swarm's conn_handler) expects ReadWriteCloser and will
            # wrap it in RawConnection itself. This matches the pattern used in
            # other transports (TCP, etc.)
            try:
                await self._handler(conn)
            except Exception as e:
                logger.error(f"Connection upgrade failed: {e}")
                self._failed_connections += 1
                # Ensure connection is closed on failure
                try:
                    await conn.close()
                except Exception:
                    pass  # Ignore errors during cleanup
            finally:
                self._untrack_connection(conn)

        except Exception as e:
            logger.error(f"Error handling WebSocket connection: {e}")
            self._failed_connections += 1

    async def close(self) -> None:
        """
        Close the listener and all connections.

        :raises WebSocketConnectionError: If closing connections fails
        """
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
            # Type guard to ensure WebSocketServer is not None
            assert WebSocketServer is not None
            # Additional type guard for the close method
            if hasattr(self._server, "close") and callable(
                getattr(self._server, "close", None)
            ):
                await self._server.close()  # type: ignore

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
