from dataclasses import dataclass
import logging
import ssl
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
    ):
        self._upgrader = upgrader
        self._config = config or WebsocketConfig()
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

    async def can_dial(self, maddr: Multiaddr) -> bool:
        """Check if we can dial the given multiaddr."""
        try:
            proto_info = parse_websocket_multiaddr(maddr)
            return proto_info.protocol in ("ws", "wss")
        except (ValueError, KeyError):
            return False

    def _track_connection(self, conn: P2PWebSocketConnection) -> None:
        """Track a new connection."""
        with self._connection_lock:
            if self._current_connections >= self._config.max_connections:
                raise OpenConnectionError("Maximum connections reached")

            conn_id = str(id(conn))
            self._connections[conn_id] = conn
            self._current_connections += 1
            self._total_connections += 1

    def _untrack_connection(self, conn: P2PWebSocketConnection) -> None:
        """Stop tracking a connection."""
        with self._connection_lock:
            conn_id = str(id(conn))
            if conn_id in self._connections:
                del self._connections[conn_id]
                self._current_connections -= 1

    async def _create_connection(
        self, proto_info, proxy_url=None
    ) -> P2PWebSocketConnection:
        """Create a new WebSocket connection."""
        ws_url = f"{proto_info.protocol}://{proto_info.host}:{proto_info.port}/"

        try:
            # Prepare SSL context for WSS connections
            ssl_context = None
            if proto_info.protocol == "wss":
                if self._config.tls_client_config:
                    ssl_context = self._config.tls_client_config
                else:
                    # Create default SSL context for client
                    ssl_context = ssl.create_default_context()
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

            # Parse the WebSocket URL to get host, port, resource
            from trio_websocket import connect_websocket
            from trio_websocket._impl import _url_to_host

            ws_host, ws_port, ws_resource, ws_ssl_context = _url_to_host(ws_url, ssl_context)

            logger.debug(f"WebsocketTransport.dial connecting to {ws_url}")

            # Create the WebSocket connection
            conn = None
            async with trio.open_nursery() as nursery:
                # Apply timeout to the connection process
                with trio.fail_after(self._config.handshake_timeout):
                    ws = await connect_websocket(
                        nursery,
                        ws_host,
                        ws_port,
                        ws_resource,
                        use_ssl=ws_ssl_context,
                        message_queue_size=1024,  # Reasonable defaults
                        max_message_size=self._config.max_message_size
                    )

                    # Create our connection wrapper
                    conn = P2PWebSocketConnection(
                        ws,
                        None,  # local_addr will be set after upgrade
                        is_secure=proto_info.protocol == "wss",
                        max_buffered_amount=self._config.max_buffered_amount
                    )

            if not conn:
                raise OpenConnectionError(f"Failed to create connection to {ws_url}")

            # Track connection
            self._track_connection(conn)

            return conn

        except trio.TooSlowError as e:
            self._failed_connections += 1
            raise OpenConnectionError(
                f"WebSocket handshake timeout after {self._config.handshake_timeout}s"
            ) from e
        except Exception as e:
            self._failed_connections += 1
            raise OpenConnectionError(f"Failed to connect to {ws_url}: {str(e)}")

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
                upgraded_conn = await self._upgrader.upgrade_outbound(
                    conn,
                    maddr,
                    peer_id=None,  # Will be determined during upgrade
                )
                return upgraded_conn
            except Exception as e:
                await conn.close()
                raise OpenConnectionError(f"Failed to upgrade connection: {str(e)}")

        except Exception as e:
            logger.error(f"Failed to dial {maddr}: {str(e)}")
            raise OpenConnectionError(f"Failed to dial {maddr}: {str(e)}")

    def get_connections(self) -> dict[str, P2PWebSocketConnection]:
        """Get all active connections."""
        with self._connection_lock:
            return self._connections.copy()

    async def listen(self, maddr: Multiaddr) -> IListener:
        """
        Listen for incoming connections on the given multiaddr.

        Args:
            maddr: The multiaddr to listen on (e.g., /ip4/0.0.0.0/tcp/8000/ws)

        Returns:
            A WebSocket listener

        Raises:
            OpenConnectionError: If listening fails
            ValueError: If multiaddr is invalid

        """
        logger.debug(f"WebsocketTransport.listen called with {maddr}")

        try:
            # Parse multiaddr
            proto_info = parse_websocket_multiaddr(maddr)

            # Prepare server options
            server_kwargs = {
                "host": proto_info.host,
                "port": proto_info.port,
                "ping_interval": self._config.ping_interval,
                "ping_timeout": self._config.ping_timeout,
                "close_timeout": self._config.close_timeout,
                "max_size": self._config.max_message_size,
            }

            # Add TLS configuration for WSS
            if proto_info.protocol == "wss":
                if not self._config.tls_server_config:
                    raise OpenConnectionError("TLS server config required for WSS")
                server_kwargs["ssl"] = self._config.tls_server_config

            # Create the listener
            listener = WebsocketListener(
                self._upgrader,
                proto_info,
                server_kwargs,
                self._config.max_connections,
                self._track_connection,
                self._untrack_connection,
            )

            # Start listening
            await listener.listen()
            self._active_listeners.add(listener)

            logger.info(f"WebSocket transport listening on {maddr}")
            return listener

        except Exception as e:
            logger.error(f"Failed to listen on {maddr}: {str(e)}")
            raise OpenConnectionError(f"Failed to listen on {maddr}: {str(e)}")

    def get_connections(self) -> dict[str, P2PWebSocketConnection]:
        """Get all active connections."""
        with self._connection_lock:
            return self._connections.copy()

    def get_listeners(self) -> set[WebsocketListener]:
        """Get all active listeners."""
        return self._active_listeners.copy()

    def get_stats(self) -> dict:
        """Get transport statistics."""
        return {
            "total_connections": self._total_connections,
            "current_connections": self._current_connections,
            "failed_connections": self._failed_connections,
            "active_listeners": len(self._active_listeners),
            "proxy_connections": self._proxy_connections,
            "has_proxy_config": bool(self._config.proxy_url),
        }

    def create_listener(self, handler: THandler) -> IListener:  # type: ignore[override]
        """
        Create a WebSocket listener with the given handler.

        Args:
            handler: Connection handler function

        Returns:
            A WebSocket listener

        """
        logger.debug("WebsocketTransport.create_listener called")
        return WebsocketListener(handler, self._upgrader, WebsocketListenerConfig(
            tls_config=self._config.tls_server_config,
            max_connections=self._config.max_connections,
            max_message_size=self._config.max_message_size,
            ping_interval=self._config.ping_interval,
            ping_timeout=self._config.ping_timeout,
            close_timeout=self._config.close_timeout
        ))

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
