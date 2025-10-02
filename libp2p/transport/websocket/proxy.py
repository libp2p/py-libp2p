import logging
import ssl
from typing import Any
from urllib.parse import urlparse

try:
    import aiohttp  # type: ignore
    import socks  # type: ignore
    from websockets.client import connect as ws_connect  # type: ignore
    from websockets.exceptions import WebSocketException  # type: ignore
except ImportError:
    # Optional dependencies - aiohttp, socks, websockets packages not installed
    aiohttp = None  # type: ignore
    socks = None  # type: ignore
    ws_connect = None  # type: ignore
    WebSocketException = Exception  # type: ignore

logger = logging.getLogger(__name__)


class SOCKSConnectionManager:
    """
    SOCKS proxy connection manager for WebSocket transport.
    Supports SOCKS4, SOCKS4a, and SOCKS5 protocols.
    """

    def __init__(
        self, proxy_url: str, auth: tuple[str, str] | None = None, timeout: float = 10.0
    ):
        """
        Initialize SOCKS proxy manager.

        Args:
            proxy_url: SOCKS proxy URL (socks5://host:port)
            auth: Optional (username, password) tuple
            timeout: Connection timeout in seconds

        """
        self.proxy_url = proxy_url
        self.auth = auth
        self.timeout = timeout

        # Parse proxy URL
        parsed = urlparse(proxy_url)
        if parsed.scheme not in ("socks4", "socks4a", "socks5", "socks5h"):
            raise ValueError(f"Unsupported proxy scheme: {parsed.scheme}")

        self.proxy_type = self._get_proxy_type(parsed.scheme)
        self.proxy_host = parsed.hostname
        self.proxy_port = parsed.port or 1080

    def _get_proxy_type(self, scheme: str) -> int:
        """Get SOCKS type from scheme."""
        if socks is None:
            raise ImportError("SOCKS proxy support requires PySocks package")
        # Type guard to ensure socks is not None
        assert socks is not None
        return {
            "socks4": socks.SOCKS4,
            "socks4a": socks.SOCKS4,
            "socks5": socks.SOCKS5,
            "socks5h": socks.SOCKS5,
        }[scheme]

    async def create_connection(
        self,
        host: str,
        port: int,
        ssl_context: bool | ssl.SSLContext | None = None,
    ) -> Any:
        """
        Create a WebSocket connection through SOCKS proxy.

        Args:
            host: Target WebSocket host
            port: Target WebSocket port
            ssl_context: Optional SSL context for WSS

        Returns:
            WebSocket connection

        Raises:
            WebSocketException: If connection fails

        """
        if socks is None or ws_connect is None:
            raise ImportError(
                "SOCKS proxy support requires PySocks and websockets packages"
            )

        try:
            # Create SOCKS connection
            sock = socks.socksocket()

            # Configure proxy
            sock.set_proxy(
                proxy_type=self.proxy_type,
                addr=self.proxy_host,
                port=self.proxy_port,
                username=self.auth[0] if self.auth else None,
                password=self.auth[1] if self.auth else None,
            )

            # Connect with timeout
            sock.settimeout(self.timeout)
            await sock.connect((host, port))

            # Create WebSocket connection using SOCKS socket
            ws = await ws_connect(
                f"{'wss' if ssl_context else 'ws'}://{host}:{port}",
                sock=sock,
                ssl=ssl_context,
                timeout=self.timeout,
            )

            return ws

        except (OSError, socks.ProxyConnectionError) as e:
            raise WebSocketException(f"SOCKS proxy connection failed: {str(e)}")
        except Exception as e:
            raise WebSocketException(f"WebSocket connection failed: {str(e)}")

    def get_proxy_info(self) -> dict[str, Any]:
        """Get proxy configuration information."""
        if socks is None:
            return {
                "type": "Unknown (SOCKS not available)",
                "host": self.proxy_host,
                "port": self.proxy_port,
                "has_auth": bool(self.auth),
            }

        # Type guard to ensure socks is not None
        assert socks is not None
        # Additional type guard for the constants
        assert hasattr(socks, "SOCKS4") and hasattr(socks, "SOCKS5")
        return {
            "type": {socks.SOCKS4: "SOCKS4", socks.SOCKS5: "SOCKS5"}[self.proxy_type],
            "host": self.proxy_host,
            "port": self.proxy_port,
            "has_auth": bool(self.auth),
        }
