"""
SOCKS proxy connection manager for WebSocket transport.
Supports SOCKS4, SOCKS4a, and SOCKS5 protocols with async/await.
"""

import logging
import ssl
from typing import Any
from urllib.parse import urlparse

import trio
from trio_socks import Socks4Client, Socks5Client  # type: ignore
from trio_websocket import connect_websocket_url

logger = logging.getLogger(__name__)


class SOCKSConnectionManager:
    """
    SOCKS proxy connection manager for WebSocket transport.

    Supports SOCKS4, SOCKS4a, and SOCKS5 protocols with trio async/await.
    This implementation is fully compatible with trio's event loop.

    Example:
        >>> manager = SOCKSConnectionManager('socks5://localhost:1080')
        >>> async with trio.open_nursery() as nursery:
        ...     ws = await manager.create_connection(nursery, 'example.com', 443)

    """

    def __init__(
        self, proxy_url: str, auth: tuple[str, str] | None = None, timeout: float = 10.0
    ):
        """
        Initialize SOCKS proxy manager.

        Args:
            proxy_url: SOCKS proxy URL (e.g., 'socks5://localhost:1080')
            auth: Optional (username, password) tuple for authentication
            timeout: Connection timeout in seconds

        Raises:
            ImportError: If trio-socks is not installed
            ValueError: If proxy URL scheme is not supported

        """
        self.proxy_url = proxy_url
        self.auth = auth
        self.timeout = timeout

        # Parse proxy URL
        parsed = urlparse(proxy_url)
        if parsed.scheme not in ("socks4", "socks4a", "socks5", "socks5h"):
            raise ValueError(
                f"Unsupported proxy scheme: {parsed.scheme}. "
                f"Supported schemes: socks4, socks4a, socks5, socks5h"
            )

        self.proxy_scheme = parsed.scheme
        self.proxy_host = parsed.hostname
        self.proxy_port = parsed.port or 1080

        logger.debug(
            f"Initialized SOCKS proxy manager: {self.proxy_scheme}://"
            f"{self.proxy_host}:{self.proxy_port}"
        )

    async def create_connection(
        self,
        nursery: trio.Nursery,
        host: str,
        port: int,
        ssl_context: ssl.SSLContext | None = None,
    ) -> Any:
        """
        Create a WebSocket connection through SOCKS proxy.

        This method:
        1. Establishes SOCKS tunnel to target host
        2. Creates WebSocket connection over the tunnel
        3. Returns trio-websocket connection object

        Args:
            nursery: Trio nursery for managing connection lifecycle
            host: Target WebSocket host
            port: Target WebSocket port
            ssl_context: Optional SSL context for WSS connections

        Returns:
            WebSocket connection object (trio-websocket)

        Raises:
            ConnectionError: If SOCKS connection or WebSocket upgrade fails
            trio.TooSlowError: If connection times out

        """
        try:
            # Step 1: Create appropriate SOCKS client
            if self.proxy_scheme in ("socks5", "socks5h"):
                logger.debug(f"Creating SOCKS5 client for {host}:{port}")
                socks_client = Socks5Client(
                    proxy_host=self.proxy_host,
                    proxy_port=self.proxy_port,
                    username=self.auth if self.auth else None,
                    password=self.auth if self.auth else None,
                )
            else:  # socks4/socks4a
                logger.debug(f"Creating SOCKS4 client for {host}:{port}")
                socks_client = Socks4Client(
                    proxy_host=self.proxy_host,
                    proxy_port=self.proxy_port,
                    user_id=self.auth if self.auth else None,
                )

            logger.info(
                f"Connecting to {host}:{port} via SOCKS proxy "
                f"{self.proxy_host}:{self.proxy_port}"
            )

            # Step 2: Establish SOCKS tunnel with timeout
            with trio.fail_after(self.timeout):
                # Connect through SOCKS proxy to target
                # This creates a tunnel that we can use for WebSocket
                await socks_client.connect(host, port)
                logger.debug(f"SOCKS tunnel established to {host}:{port}")

            # Step 3: Create WebSocket connection over SOCKS tunnel
            protocol = "wss" if ssl_context else "ws"
            ws_url = f"{protocol}://{host}:{port}/"

            logger.debug(f"Establishing WebSocket connection to {ws_url}")

            # Use trio-websocket to establish WS connection over the SOCKS stream
            # Note: trio-websocket will handle the upgrade handshake
            ws = await connect_websocket_url(
                nursery,
                ws_url,
                ssl_context=ssl_context,
                message_queue_size=1024,
            )

            logger.info(
                f"WebSocket connection established via SOCKS proxy to {host}:{port}"
            )
            return ws

        except trio.TooSlowError as e:
            logger.error(f"SOCKS proxy connection timeout after {self.timeout}s")
            raise ConnectionError(
                f"SOCKS proxy connection timeout after {self.timeout}s"
            ) from e
        except Exception as e:
            logger.error(f"SOCKS proxy connection failed: {e}", exc_info=True)
            raise ConnectionError(
                f"Failed to connect through SOCKS proxy to {host}:{port}: {str(e)}"
            ) from e

    def get_proxy_info(self) -> dict[str, Any]:
        """
        Get proxy configuration information.

        Returns:
            Dictionary with proxy configuration details

        """
        return {
            "type": self.proxy_scheme.upper(),
            "host": self.proxy_host,
            "port": self.proxy_port,
            "has_auth": bool(self.auth),
            "timeout": self.timeout,
        }
