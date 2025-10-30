import logging
import ssl

from multiaddr import Multiaddr

from libp2p.abc import IListener, ITransport
from libp2p.custom_types import THandler
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.multiaddr_utils import parse_websocket_multiaddr

from .connection import P2PWebSocketConnection
from .listener import WebsocketListener

logger = logging.getLogger(__name__)


class WebsocketTransport(ITransport):
    """
    Libp2p WebSocket transport: dial and listen on /ip4/.../tcp/.../ws and /wss

    Implements production-ready WebSocket transport with:
    - Flow control and buffer management
    - Connection limits and rate limiting
    - Proper error handling and cleanup
    - Support for both WS and WSS protocols
    - TLS configuration and handshake timeout
    """

    def __init__(
        self,
        upgrader: TransportUpgrader,
        tls_client_config: ssl.SSLContext | None = None,
        tls_server_config: ssl.SSLContext | None = None,
        handshake_timeout: float = 15.0,
        max_buffered_amount: int = 4 * 1024 * 1024,
    ):
        self._upgrader = upgrader
        self._tls_client_config = tls_client_config
        self._tls_server_config = tls_server_config
        self._handshake_timeout = handshake_timeout
        self._max_buffered_amount = max_buffered_amount
        self._connection_count = 0
        self._max_connections = 1000  # Production limit

    async def dial(self, maddr: Multiaddr) -> RawConnection:
        """Dial a WebSocket connection to the given multiaddr."""
        logger.debug(f"WebsocketTransport.dial called with {maddr}")

        # Parse the WebSocket multiaddr to determine if it's secure
        try:
            parsed = parse_websocket_multiaddr(maddr)
        except ValueError as e:
            raise ValueError(f"Invalid WebSocket multiaddr: {e}") from e

        # Extract host and port from the base multiaddr
        host = (
            parsed.rest_multiaddr.value_for_protocol("ip4")
            or parsed.rest_multiaddr.value_for_protocol("ip6")
            or parsed.rest_multiaddr.value_for_protocol("dns")
            or parsed.rest_multiaddr.value_for_protocol("dns4")
            or parsed.rest_multiaddr.value_for_protocol("dns6")
        )
        port_str = parsed.rest_multiaddr.value_for_protocol("tcp")
        if port_str is None:
            raise ValueError(f"No TCP port found in multiaddr: {maddr}")
        port = int(port_str)

        # Build WebSocket URL based on security
        if parsed.is_wss:
            ws_url = f"wss://{host}:{port}/"
        else:
            ws_url = f"ws://{host}:{port}/"

        logger.debug(
            f"WebsocketTransport.dial connecting to {ws_url} (secure={parsed.is_wss})"
        )

        try:
            # Check connection limits
            if self._connection_count >= self._max_connections:
                raise OpenConnectionError(
                    f"Maximum connections reached: {self._max_connections}"
                )

            # Prepare SSL context for WSS connections
            ssl_context = None
            if parsed.is_wss:
                if self._tls_client_config:
                    ssl_context = self._tls_client_config
                else:
                    # Create default SSL context for client
                    ssl_context = ssl.create_default_context()
                    # Set SNI if available
                    if parsed.sni:
                        ssl_context.check_hostname = False
                        ssl_context.verify_mode = ssl.CERT_NONE

            logger.debug(f"WebsocketTransport.dial opening connection to {ws_url}")

            # Use a different approach: start background nursery that will persist
            logger.debug("WebsocketTransport.dial establishing connection")

            # Import trio-websocket functions
            from trio_websocket import connect_websocket
            from trio_websocket._impl import _url_to_host

            # Parse the WebSocket URL to get host, port, resource
            # like trio-websocket does
            ws_host, ws_port, ws_resource, ws_ssl_context = _url_to_host(
                ws_url, ssl_context
            )

            logger.debug(
                f"WebsocketTransport.dial parsed URL: host={ws_host}, "
                f"port={ws_port}, resource={ws_resource}"
            )

            # Create a background task manager for this connection
            import trio

            nursery_manager = trio.lowlevel.current_task().parent_nursery
            if nursery_manager is None:
                raise OpenConnectionError(
                    f"No parent nursery available for WebSocket connection to {maddr}"
                )

            # Apply timeout to the connection process
            with trio.fail_after(self._handshake_timeout):
                logger.debug("WebsocketTransport.dial connecting WebSocket")
                ws = await connect_websocket(
                    nursery_manager,  # Use the existing nursery from libp2p
                    ws_host,
                    ws_port,
                    ws_resource,
                    use_ssl=ws_ssl_context,
                    message_queue_size=1024,  # Reasonable defaults
                    max_message_size=16 * 1024 * 1024,  # 16MB max message
                )
                logger.debug("WebsocketTransport.dial WebSocket connection established")

                # Create our connection wrapper with both WSS support and flow control
                conn = P2PWebSocketConnection(
                    ws,
                    None,
                    is_secure=parsed.is_wss,
                    max_buffered_amount=self._max_buffered_amount,
                )
                logger.debug("WebsocketTransport.dial created P2PWebSocketConnection")

                self._connection_count += 1
                logger.debug(f"Total connections: {self._connection_count}")

                return RawConnection(conn, initiator=True)
        except trio.TooSlowError as e:
            raise OpenConnectionError(
                f"WebSocket handshake timeout after {self._handshake_timeout}s "
                f"for {maddr}"
            ) from e
        except Exception as e:
            logger.error(f"Failed to dial WebSocket {maddr}: {e}")
            raise OpenConnectionError(f"Failed to dial WebSocket {maddr}: {e}") from e

    def create_listener(self, handler: THandler) -> IListener:  # type: ignore[override]
        """
        The type checker is incorrectly reporting this as an inconsistent override.
        """
        logger.debug("WebsocketTransport.create_listener called")
        return WebsocketListener(
            handler, self._upgrader, self._tls_server_config, self._handshake_timeout
        )

    def resolve(self, maddr: Multiaddr) -> list[Multiaddr]:
        """
        Resolve a WebSocket multiaddr, automatically adding SNI for DNS names.
        Similar to Go's Resolve() method.

        :param maddr: The multiaddr to resolve
        :return: List of resolved multiaddrs
        """
        try:
            parsed = parse_websocket_multiaddr(maddr)
        except ValueError as e:
            logger.debug(f"Invalid WebSocket multiaddr for resolution: {e}")
            return [maddr]  # Return original if not a valid WebSocket multiaddr

        logger.debug(
            f"Parsed multiaddr {maddr}: is_wss={parsed.is_wss}, sni={parsed.sni}"
        )

        if not parsed.is_wss:
            # No /tls/ws component, this isn't a secure websocket multiaddr
            return [maddr]

        if parsed.sni is not None:
            # Already has SNI, return as-is
            return [maddr]

        # Try to extract DNS name from the base multiaddr
        dns_name = None
        for protocol_name in ["dns", "dns4", "dns6"]:
            try:
                dns_name = parsed.rest_multiaddr.value_for_protocol(protocol_name)
                break
            except Exception:
                continue

        if dns_name is None:
            # No DNS name found, return original
            return [maddr]

        # Create new multiaddr with SNI
        # For /dns/example.com/tcp/8080/wss ->
        # /dns/example.com/tcp/8080/tls/sni/example.com/ws
        try:
            # Remove /wss and add /tls/sni/example.com/ws
            without_wss = maddr.decapsulate(Multiaddr("/wss"))
            sni_component = Multiaddr(f"/sni/{dns_name}")
            resolved = (
                without_wss.encapsulate(Multiaddr("/tls"))
                .encapsulate(sni_component)
                .encapsulate(Multiaddr("/ws"))
            )
            logger.debug(f"Resolved {maddr} to {resolved}")
            return [resolved]
        except Exception as e:
            logger.debug(f"Failed to resolve multiaddr {maddr}: {e}")
            return [maddr]
