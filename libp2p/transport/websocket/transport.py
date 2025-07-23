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
        # Handle addresses with /p2p/ PeerID suffix by truncating them at /ws
        addr_text = str(maddr)
        try:
            ws_part_index = addr_text.index("/ws")
            # Create a new Multiaddr containing only the transport part
            transport_maddr = Multiaddr(addr_text[: ws_part_index + 3])
        except ValueError:
            raise ValueError(
                f"WebsocketTransport requires a /ws protocol, not found in {maddr}"
            ) from None

        # Check for /wss, which is not supported yet
        if str(transport_maddr).endswith("/wss"):
            raise NotImplementedError("/wss (TLS) not yet supported")

        host = (
            transport_maddr.value_for_protocol("ip4")
            or transport_maddr.value_for_protocol("ip6")
            or transport_maddr.value_for_protocol("dns")
            or transport_maddr.value_for_protocol("dns4")
            or transport_maddr.value_for_protocol("dns6")
        )
        if host is None:
            raise ValueError(f"No host protocol found in {transport_maddr}")

        port_str = transport_maddr.value_for_protocol("tcp")
        if port_str is None:
            raise ValueError(f"No TCP port found in multiaddr: {transport_maddr}")
        port = int(port_str)

        host_str = f"[{host}]" if ":" in host else host
        uri = f"ws://{host_str}:{port}"

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
