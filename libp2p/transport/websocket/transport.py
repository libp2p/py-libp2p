import logging

from multiaddr import Multiaddr

from libp2p.abc import IListener, ITransport
from libp2p.custom_types import THandler
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.upgrader import TransportUpgrader

from .connection import P2PWebSocketConnection
from .listener import WebsocketListener

logger = logging.getLogger(__name__)


class WebsocketTransport(ITransport):
    """
    Libp2p WebSocket transport: dial and listen on /ip4/.../tcp/.../ws
    """

    def __init__(self, upgrader: TransportUpgrader):
        self._upgrader = upgrader

    async def dial(self, maddr: Multiaddr) -> RawConnection:
        """Dial a WebSocket connection to the given multiaddr."""
        logger.debug(f"WebsocketTransport.dial called with {maddr}")

        # Extract host and port from multiaddr
        host = (
            maddr.value_for_protocol("ip4")
            or maddr.value_for_protocol("ip6")
            or maddr.value_for_protocol("dns")
            or maddr.value_for_protocol("dns4")
            or maddr.value_for_protocol("dns6")
        )
        port_str = maddr.value_for_protocol("tcp")
        if port_str is None:
            raise ValueError(f"No TCP port found in multiaddr: {maddr}")
        port = int(port_str)

        # Build WebSocket URL
        ws_url = f"ws://{host}:{port}/"
        logger.debug(f"WebsocketTransport.dial connecting to {ws_url}")

        try:
            from trio_websocket import open_websocket_url

            # Use the context manager but don't exit it immediately
            # The connection will be closed when the RawConnection is closed
            ws_context = open_websocket_url(ws_url)
            ws = await ws_context.__aenter__()
            conn = P2PWebSocketConnection(ws, ws_context)  # type: ignore[attr-defined]
            return RawConnection(conn, initiator=True)
        except Exception as e:
            raise OpenConnectionError(f"Failed to dial WebSocket {maddr}: {e}") from e

    def create_listener(self, handler: THandler) -> IListener:  # type: ignore[override]
        """
        The type checker is incorrectly reporting this as an inconsistent override.
        """
        logger.debug("WebsocketTransport.create_listener called")
        return WebsocketListener(handler, self._upgrader)
