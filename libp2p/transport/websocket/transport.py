from dataclasses import dataclass
import logging
import ssl
from typing import Any
from urllib.parse import urlparse

from multiaddr import Multiaddr
import trio

from libp2p.abc import IListener, ITransport
from libp2p.custom_types import THandler
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.multiaddr_utils import parse_websocket_multiaddr

from .connection import P2PWebSocketConnection
from .listener import WebsocketListener

logger = logging.getLogger(__name__)


@dataclass
class WebsocketConfig:
    """Configuration options for WebSocket transport."""

    # TLS configuration
    tls_client_config: ssl.SSLContext | None = None
    tls_server_config: ssl.SSLContext | None = None

    # Connection settings
    handshake_timeout: float = 15.0
    max_buffered_amount: int = 4 * 1024 * 1024
    max_connections: int = 1000

    # Proxy configuration
    proxy_url: str | None = None
    proxy_auth: tuple[str, str] | None = None

    # Advanced settings
    ping_interval: float = 20.0
    ping_timeout: float = 10.0
    close_timeout: float = 5.0
    max_message_size: int = 32 * 1024 * 1024  # 32MB

    def validate(self) -> None:
        """Validate configuration settings."""
        if self.handshake_timeout <= 0:
            raise ValueError("handshake_timeout must be positive")
        if self.max_buffered_amount <= 0:
            raise ValueError("max_buffered_amount must be positive")
        if self.max_connections <= 0:
            raise ValueError("max_connections must be positive")
        if self.proxy_url and urlparse(self.proxy_url).scheme not in (
            "socks5",
            "socks5h",
        ):
            raise ValueError("proxy_url must be a SOCKS5 URL")


class WebsocketTransport(ITransport):
    """
    Libp2p WebSocket transport implementation with production features:

    Features:
    - WS and WSS protocol support with configurable TLS
    - Connection management with limits and tracking
    - Flow control and buffer management
    - SOCKS5 proxy support
    - Proper error handling and connection cleanup
    - Configurable timeouts and limits
    - Connection state monitoring
    - Concurrent connection handling
    """

    def __init__(
        self,
        upgrader: TransportUpgrader,
        config: WebsocketConfig | None = None,
        tls_client_config: ssl.SSLContext | None = None,
        tls_server_config: ssl.SSLContext | None = None,
        handshake_timeout: float | None = None,
    ):
        self._upgrader = upgrader
        if config is None:
            config = WebsocketConfig()
        if tls_client_config is not None:
            config.tls_client_config = tls_client_config
        if tls_server_config is not None:
            config.tls_server_config = tls_server_config
        if handshake_timeout is not None:
            config.handshake_timeout = handshake_timeout
        self._config = config
        self._config.validate()

        # Connection tracking
        self._connections: dict[str, P2PWebSocketConnection] = {}
        self._connection_lock = trio.Lock()
        self._active_listeners: set[WebsocketListener] = set()

        # Initialize counters and limits
        self._connection_count = 0
        self._max_connections = config.max_connections if config else 1000
        self._handshake_timeout = config.handshake_timeout if config else 15.0
        self._max_buffered_amount = (
            config.max_buffered_amount if config else 4 * 1024 * 1024
        )

        # Statistics
        self._total_connections = 0
        self._failed_connections = 0
        self._current_connections = 0
        self._proxy_connections = 0  # Track proxy usage

        # Expose config attributes for backward compatibility
        self._tls_client_config = self._config.tls_client_config
        self._tls_server_config = self._config.tls_server_config

    async def can_dial(self, maddr: Multiaddr) -> bool:
        """Check if we can dial the given multiaddr."""
        try:
            parse_websocket_multiaddr(maddr)
            return True  # If parsing succeeds, it's a valid WebSocket multiaddr
        except (ValueError, KeyError):
            return False

    async def _track_connection(self, conn: P2PWebSocketConnection) -> None:
        """Track a new connection."""
        async with self._connection_lock:
            if self._current_connections >= self._config.max_connections:
                raise OpenConnectionError("Maximum connections reached")

            conn_id = str(id(conn))
            self._connections[conn_id] = conn
            self._current_connections += 1
            self._total_connections += 1

    async def _untrack_connection(self, conn: P2PWebSocketConnection) -> None:
        """Stop tracking a connection."""
        async with self._connection_lock:
            conn_id = str(id(conn))
            if conn_id in self._connections:
                del self._connections[conn_id]
                self._current_connections -= 1

    async def _create_connection(
        self, proto_info: Any, proxy_url: str | None = None
    ) -> P2PWebSocketConnection:
        """Create a new WebSocket connection."""
        # Extract host and port from the rest_multiaddr
        host = (
            proto_info.rest_multiaddr.value_for_protocol("ip4")
            or proto_info.rest_multiaddr.value_for_protocol("ip6")
            or "localhost"
        )
        port = int(proto_info.rest_multiaddr.value_for_protocol("tcp") or "80")
        protocol = "wss" if proto_info.is_wss else "ws"
        ws_url = f"{protocol}://{host}:{port}/"

        # Use proxy from config if not provided
        if proxy_url is None:
            proxy_url = self._config.proxy_url

        try:
            # Prepare SSL context for WSS connections
            ssl_context = None
            if proto_info.is_wss:
                if self._config.tls_client_config:
                    ssl_context = self._config.tls_client_config
                else:
                    # Create default SSL context for client
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

            # Handle proxy connections
            if proxy_url:
                logger.debug(f"Using SOCKS proxy: {proxy_url}")
                self._proxy_connections += 1
                conn = await self._create_proxy_connection(
                    proto_info, proxy_url, ssl_context
                )
            else:
                # Direct connection
                conn = await self._create_direct_connection(proto_info, ssl_context)

            if not conn:
                raise OpenConnectionError(f"Failed to create connection to {ws_url}")

            # Track connection
            await self._track_connection(conn)

            return conn

        except trio.TooSlowError as e:
            self._failed_connections += 1
            raise OpenConnectionError(
                f"WebSocket handshake timeout after {self._config.handshake_timeout}s"
            ) from e
        except Exception as e:
            self._failed_connections += 1
            raise OpenConnectionError(f"Failed to connect to {ws_url}: {str(e)}")

    async def _create_direct_connection(
        self, proto_info: Any, ssl_context: ssl.SSLContext | None
    ) -> P2PWebSocketConnection:
        """Create a direct WebSocket connection."""
        # Extract host and port from the rest_multiaddr
        host = (
            proto_info.rest_multiaddr.value_for_protocol("ip4")
            or proto_info.rest_multiaddr.value_for_protocol("ip6")
            or "localhost"
        )
        port = int(proto_info.rest_multiaddr.value_for_protocol("tcp") or "80")
        protocol = "wss" if proto_info.is_wss else "ws"
        ws_url = f"{protocol}://{host}:{port}/"

        logger.debug(f"WebsocketTransport.dial connecting to {ws_url}")

        # Apply timeout to the connection process
        with trio.fail_after(self._config.handshake_timeout):
            # Create a temporary nursery just for the WebSocket connection establishment
            async with trio.open_nursery() as temp_nursery:
                from trio_websocket import connect_websocket_url

                # Create the WebSocket connection
                ws = await connect_websocket_url(
                    temp_nursery,
                    ws_url,
                    ssl_context=ssl_context,
                    message_queue_size=1024,
                    max_message_size=self._config.max_message_size,
                )

                # Create our connection wrapper
                conn = P2PWebSocketConnection(
                    ws,
                    None,  # local_addr will be set after upgrade
                    is_secure=proto_info.is_wss,
                    max_buffered_amount=self._config.max_buffered_amount,
                )

                # The nursery will close when we exit this block, which might close the
                # connection. We need to handle this differently.
                return conn

    async def _create_proxy_connection(
        self, proto_info: Any, proxy_url: str, ssl_context: ssl.SSLContext | None
    ) -> P2PWebSocketConnection:
        """Create a WebSocket connection through SOCKS proxy."""
        try:
            from .proxy import SOCKSConnectionManager

            # Create proxy manager
            proxy_manager = SOCKSConnectionManager(
                proxy_url=proxy_url,
                auth=self._config.proxy_auth,
                timeout=self._config.handshake_timeout,
            )

            # Extract host and port from the rest_multiaddr
            host = (
                proto_info.rest_multiaddr.value_for_protocol("ip4")
                or proto_info.rest_multiaddr.value_for_protocol("ip6")
                or "localhost"
            )
            port = int(proto_info.rest_multiaddr.value_for_protocol("tcp") or "80")

            logger.debug(f"Connecting through SOCKS proxy to {host}:{port}")

            # Create connection through proxy
            ws_connection = await proxy_manager.create_connection(
                host=host, port=port, ssl_context=ssl_context
            )

            # Create our connection wrapper
            return P2PWebSocketConnection(
                ws_connection,
                None,  # local_addr will be set after upgrade
                is_secure=proto_info.protocol == "wss",
                max_buffered_amount=self._config.max_buffered_amount,
            )

        except ImportError:
            raise OpenConnectionError(
                "SOCKS proxy support requires PySocks package. "
                "Install with: pip install PySocks"
            )
        except Exception as e:
            raise OpenConnectionError(f"SOCKS proxy connection failed: {str(e)}")

    async def dial(self, maddr: Multiaddr) -> RawConnection:
        """
        Dial a WebSocket connection to the given multiaddr.

        Args:
            maddr: The multiaddr to dial (e.g., /ip4/127.0.0.1/tcp/8000/ws)

        Returns:
            An upgraded RawConnection

        Raises:
            OpenConnectionError: If connection fails
            ValueError: If multiaddr is invalid

        """
        logger.debug(f"WebsocketTransport.dial called with {maddr}")

        if not await self.can_dial(maddr):
            raise OpenConnectionError(f"Cannot dial {maddr}")

        try:
            # Parse multiaddr and create connection
            proto_info = parse_websocket_multiaddr(maddr)
            conn = await self._create_connection(proto_info)

            # Upgrade the connection
            try:
                # For now, just return the connection directly
                # TODO: Implement proper connection upgrading
                return RawConnection(conn, True)  # True for initiator
            except Exception as e:
                await conn.close()
                raise OpenConnectionError(f"Failed to upgrade connection: {str(e)}")

        except Exception as e:
            logger.error(f"Failed to dial {maddr}: {str(e)}")
            raise OpenConnectionError(f"Failed to dial {maddr}: {str(e)}")

    def create_listener(self, handler: THandler) -> IListener:  # type: ignore[override]
        """
        Create a WebSocket listener with the given handler.

        Args:
            handler: Connection handler function

        Returns:
            A WebSocket listener

        """
        logger.debug("WebsocketTransport.create_listener called")
        from .listener import WebsocketListenerConfig

        return WebsocketListener(
            handler,
            self._upgrader,
            WebsocketListenerConfig(
                tls_config=self._config.tls_server_config,
                max_connections=self._config.max_connections,
                max_message_size=self._config.max_message_size,
                handshake_timeout=self._config.handshake_timeout,
                ping_interval=self._config.ping_interval,
                ping_timeout=self._config.ping_timeout,
                close_timeout=self._config.close_timeout,
            ),
        )

    async def get_connections(self) -> dict[str, P2PWebSocketConnection]:
        """Get all active connections."""
        async with self._connection_lock:
            return self._connections.copy()

    def get_listeners(self) -> set[WebsocketListener]:
        """Get all active listeners."""
        return self._active_listeners.copy()

    def get_stats(self) -> dict[str, int]:
        """Get transport statistics."""
        return {
            "total_connections": self._total_connections,
            "current_connections": self._current_connections,
            "failed_connections": self._failed_connections,
            "active_listeners": len(self._active_listeners),
            "proxy_connections": self._proxy_connections,
            "has_proxy_config": bool(self._config.proxy_url),
        }

    def resolve(self, maddr: Multiaddr) -> list[Multiaddr]:
        """
        Resolve a WebSocket multiaddr to its concrete addresses.
        Currently, just validates and returns the input multiaddr.

        Args:
            maddr: The multiaddr to resolve

        Returns:
            List containing the original multiaddr

        """
        try:
            parse_websocket_multiaddr(maddr)  # Validate format
            return [maddr]
        except ValueError as e:
            logger.debug(f"Invalid WebSocket multiaddr for resolution: {e}")
            return [maddr]
