import asyncio
import logging
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set, Union

import trio
from multiaddr import Multiaddr
from trio_typing import TaskStatus
from trio_websocket import WebSocketConnection, serve_websocket
from websockets.server import WebSocketServer

from libp2p.abc import IListener
from libp2p.custom_types import THandler
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.multiaddr_utils import parse_websocket_multiaddr

from .connection import P2PWebSocketConnection

logger = logging.getLogger("libp2p.transport.websocket.listener")


@dataclass
class WebsocketListenerConfig:
    """Configuration for WebSocket listener."""

    # TLS configuration
    tls_config: Optional[ssl.SSLContext] = None

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
    - Connection state monitoring
    """

    def __init__(
        self,
        handler: THandler,
        upgrader: TransportUpgrader,
        config: Optional[WebsocketListenerConfig] = None,
    ) -> None:
        """
        Initialize a new WebSocket listener.

        Args:
            handler: Connection handler function
            upgrader: Transport upgrader
            config: Optional listener configuration
        """
        self._handler = handler
        self._upgrader = upgrader
        self._config = config or WebsocketListenerConfig()

        # State tracking
        self._active_connections: Set[P2PWebSocketConnection] = set()
        self._server: Optional[WebSocketServer] = None
        self._nursery: Optional[trio.Nursery] = None
        self._closed = False
        self._listen_maddr: Optional[Multiaddr] = None

        # Statistics
        self._total_connections = 0
        self._current_connections = 0
        self._failed_connections = 0

    def _can_accept_connection(self) -> bool:
        """Check if we can accept a new connection."""
        return (
            not self._closed
            and self._current_connections < self._config.max_connections
        )

    async def handle_connection(self, ws: WebSocketConnection) -> None:
        """
        Handle a new WebSocket connection.

        Args:
            ws: The WebSocket connection
        """
        if not self._can_accept_connection():
            logger.warning("Maximum connections reached, rejecting connection")
            await ws.close(code=1013)  # Try again later
            return

        # Create connection wrapper
        conn = P2PWebSocketConnection(
            ws,
            local_addr=self._listen_maddr,
            remote_addr=None,  # Set during upgrade
            max_buffer=self._config.max_message_size
        )

        try:
            # Track connection
            self._active_connections.add(conn)
            self._current_connections += 1
            self._total_connections += 1

            # Upgrade connection
            upgraded_conn = await self._upgrader.upgrade_inbound(conn)

            # Handle upgraded connection
            await self._handler(upgraded_conn)

        except Exception as e:
            logger.error(f"Error handling connection: {e}")
            self._failed_connections += 1
            await conn.close()

        finally:
            # Cleanup
            self._active_connections.remove(conn)
            self._current_connections -= 1

    async def listen(self, maddr: Multiaddr) -> None:
        """
        Start listening for connections.

        Args:
            maddr: The multiaddr to listen on

        Raises:
            OpenConnectionError: If listening fails
        """
        if self._closed:
            raise OpenConnectionError("Listener is closed")

        try:
            # Parse multiaddr
            proto_info = parse_websocket_multiaddr(maddr)
            self._listen_maddr = maddr

            # Prepare server options
            ssl_context = None
            if proto_info.protocol == "wss":
                if not self._config.tls_config:
                    raise OpenConnectionError("TLS config required for WSS")
                ssl_context = self._config.tls_config

            # Start server
            async with trio.open_nursery() as nursery:
                self._nursery = nursery
                await serve_websocket(
                    handler=self.handle_connection,
                    host=proto_info.host,
                    port=proto_info.port,
                    ssl_context=ssl_context,
                    handler_nursery=nursery,
                )

                logger.info(f"WebSocket listener started on {maddr}")

        except Exception as e:
            logger.error(f"Failed to start listener: {e}")
            raise OpenConnectionError(f"Failed to start listener: {e}")

    def multiaddr(self) -> Multiaddr:
        """Get the listening multiaddr."""
        if not self._listen_maddr:
            raise RuntimeError("Listener not started")
        return self._listen_maddr

    async def close(self) -> None:
        """Close the listener and all connections."""
        if self._closed:
            return

        self._closed = True

        # Close all active connections
        for conn in list(self._active_connections):
            await conn.close()

        # Cancel nursery tasks
        if self._nursery:
            self._nursery.cancel_scope.cancel()

        logger.info(f"WebSocket listener closed on {self._listen_maddr}")

    @property
    def is_closed(self) -> bool:
        """Check if the listener is closed."""
        return self._closed

    def get_stats(self) -> Dict[str, int]:
        """Get listener statistics."""
        return {
            "total_connections": self._total_connections,
            "current_connections": self._current_connections,
            "failed_connections": self._failed_connections
        }
        self._handler = handler
        self._upgrader = upgrader
        self._tls_config = tls_config
        self._handshake_timeout = handshake_timeout
        self._server = None
        self._shutdown_event = trio.Event()
        self._nursery: trio.Nursery | None = None
        self._listeners: Any = None
        self._is_wss = False  # Track whether this is a WSS listener

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        logger.debug(f"WebsocketListener.listen called with {maddr}")

        # Parse the WebSocket multiaddr to determine if it's secure
        try:
            parsed = parse_websocket_multiaddr(maddr)
        except ValueError as e:
            raise ValueError(f"Invalid WebSocket multiaddr: {e}") from e

        # Check if WSS is requested but no TLS config provided
        if parsed.is_wss and self._tls_config is None:
            raise ValueError(
                f"Cannot listen on WSS address {maddr} without TLS configuration"
            )

        # Store whether this is a WSS listener
        self._is_wss = parsed.is_wss

        # Extract host and port from the base multiaddr
        host = (
            parsed.rest_multiaddr.value_for_protocol("ip4")
            or parsed.rest_multiaddr.value_for_protocol("ip6")
            or parsed.rest_multiaddr.value_for_protocol("dns")
            or parsed.rest_multiaddr.value_for_protocol("dns4")
            or parsed.rest_multiaddr.value_for_protocol("dns6")
            or "0.0.0.0"
        )
        port_str = parsed.rest_multiaddr.value_for_protocol("tcp")
        if port_str is None:
            raise ValueError(f"No TCP port found in multiaddr: {maddr}")
        port = int(port_str)

        logger.debug(
            f"WebsocketListener: host={host}, port={port}, secure={parsed.is_wss}"
        )

        async def serve_websocket_tcp(
            handler: Callable[[Any], Awaitable[None]],
            port: int,
            host: str,
            task_status: TaskStatus[Any],
        ) -> None:
            """Start TCP server and handle WebSocket connections manually"""
            logger.debug(
                "serve_websocket_tcp %s %s (secure=%s)", host, port, parsed.is_wss
            )

            async def websocket_handler(request: Any) -> None:
                """Handle WebSocket requests"""
                logger.debug("WebSocket request received")
                try:
                    # Apply handshake timeout
                    with trio.fail_after(self._handshake_timeout):
                        # Accept the WebSocket connection
                        ws_connection = await request.accept()
                        logger.debug("WebSocket handshake successful")

                        # Create the WebSocket connection wrapper
                        conn = P2PWebSocketConnection(
                            ws_connection, is_secure=parsed.is_wss
                        )  # type: ignore[no-untyped-call]

                        # Call the handler function that was passed to create_listener
                        # This handler will handle the security and muxing upgrades
                        logger.debug("Calling connection handler")
                        await self._handler(conn)

                        # Don't keep the connection alive indefinitely
                        # Let the handler manage the connection lifecycle
                        logger.debug(
                            "Handler completed, connection will be managed by handler"
                        )

                except trio.TooSlowError:
                    logger.debug(
                        f"WebSocket handshake timeout after {self._handshake_timeout}s"
                    )
                    try:
                        await request.reject(408)  # Request Timeout
                    except Exception:
                        pass
                except Exception as e:
                    logger.debug(f"WebSocket connection error: {e}")
                    logger.debug(f"Error type: {type(e)}")
                    import traceback

                    logger.debug(f"Traceback: {traceback.format_exc()}")
                    # Reject the connection
                    try:
                        await request.reject(400)
                    except Exception:
                        pass

            # Use trio_websocket.serve_websocket for proper WebSocket handling
            ssl_context = self._tls_config if parsed.is_wss else None
            await serve_websocket(
                websocket_handler, host, port, ssl_context, task_status=task_status
            )

        # Store the nursery for shutdown
        self._nursery = nursery

        # Start the server using nursery.start() like TCP does
        logger.debug("Calling nursery.start()...")
        started_listeners = await nursery.start(
            serve_websocket_tcp,
            None,  # No handler needed since it's defined inside serve_websocket_tcp
            port,
            host,
        )
        logger.debug(f"nursery.start() returned: {started_listeners}")

        if started_listeners is None:
            logger.error(f"Failed to start WebSocket listener for {maddr}")
            return False

        # Store the listeners for get_addrs() and close() - these are real
        # SocketListener objects
        self._listeners = started_listeners
        logger.debug(
            "WebsocketListener.listen returning True with WebSocketServer object"
        )
        return True

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        if not hasattr(self, "_listeners") or not self._listeners:
            logger.debug("No listeners available for get_addrs()")
            return ()

        # Handle WebSocketServer objects
        if hasattr(self._listeners, "port"):
            # This is a WebSocketServer object
            port = self._listeners.port
            # Create a multiaddr from the port with correct WSS/WS protocol
            protocol = "wss" if self._is_wss else "ws"
            return (Multiaddr(f"/ip4/127.0.0.1/tcp/{port}/{protocol}"),)
        else:
            # This is a list of listeners (like TCP)
            listeners = self._listeners
            # Get addresses from listeners like TCP does
            return tuple(
                _multiaddr_from_socket(listener.socket, self._is_wss)
                for listener in listeners
            )

    async def close(self) -> None:
        """Close the WebSocket listener and stop accepting new connections"""
        logger.debug("WebsocketListener.close called")
        if hasattr(self, "_listeners") and self._listeners:
            # Signal shutdown
            self._shutdown_event.set()

            # Close the WebSocket server
            if hasattr(self._listeners, "aclose"):
                # This is a WebSocketServer object
                logger.debug("Closing WebSocket server")
                await self._listeners.aclose()
                logger.debug("WebSocket server closed")
            elif isinstance(self._listeners, (list, tuple)):
                # This is a list of listeners (like TCP)
                logger.debug("Closing TCP listeners")
                for listener in self._listeners:
                    await listener.aclose()
                logger.debug("TCP listeners closed")
            else:
                # Unknown type, try to close it directly
                logger.debug("Closing unknown listener type")
                if hasattr(self._listeners, "close"):
                    self._listeners.close()
                logger.debug("Unknown listener closed")

            # Clear the listeners reference
            self._listeners = None
            logger.debug("WebsocketListener.close completed")


def _multiaddr_from_socket(
    socket: trio.socket.SocketType, is_wss: bool = False
) -> Multiaddr:
    """Convert socket to multiaddr"""
    ip, port = socket.getsockname()
    protocol = "wss" if is_wss else "ws"
    return Multiaddr(f"/ip4/{ip}/tcp/{port}/{protocol}")
