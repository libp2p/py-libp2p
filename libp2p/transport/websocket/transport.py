from multiaddr import Multiaddr
from trio_websocket import open_websocket_url

from libp2p.abc import IListener, ITransport
from libp2p.custom_types import THandler
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.transport.exceptions import OpenConnectionError

from .connection import P2PWebSocketConnection
from .listener import WebsocketListener


class WebsocketTransport(ITransport):
    """
    Libp2p WebSocket transport: dial and listen on /ip4/.../tcp/.../ws
    """

    async def dial(self, maddr: Multiaddr) -> RawConnection:
        text = str(maddr)
        if text.endswith("/wss"):
            raise NotImplementedError("/wss (TLS) not yet supported")
        if not text.endswith("/ws"):
            raise ValueError(f"WebsocketTransport only supports /ws, got {maddr}")

        host = (
            maddr.value_for_protocol("ip4")
            or maddr.value_for_protocol("ip6")
            or maddr.value_for_protocol("dns")
            or maddr.value_for_protocol("dns4")
            or maddr.value_for_protocol("dns6")
        )
        if host is None:
            raise ValueError(f"No host protocol found in {maddr}")

        port = int(maddr.value_for_protocol("tcp"))
        uri = f"ws://{host}:{port}"

        try:
            async with open_websocket_url(uri, ssl_context=None) as ws:
                conn = P2PWebSocketConnection(ws.stream)  # type: ignore[attr-defined]
                return RawConnection(conn, initiator=True)
        except Exception as e:
            raise OpenConnectionError(f"Failed to dial WebSocket {maddr}: {e}") from e

    def create_listener(self, handler: THandler) -> IListener:  # type: ignore[override]
        """
        The type checker is incorrectly reporting this as an inconsistent override.
        """
        return WebsocketListener(handler)
