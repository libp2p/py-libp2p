import logging
import socket
from typing import Any

from multiaddr import Multiaddr
import trio
from trio_typing import TaskStatus
from trio_websocket import serve_websocket

from libp2p.abc import IListener
from libp2p.custom_types import THandler
from libp2p.network.connection.raw_connection import RawConnection

from .connection import P2PWebSocketConnection

logger = logging.getLogger("libp2p.transport.websocket.listener")


class WebsocketListener(IListener):
    """
    Listen on /ip4/.../tcp/.../ws addresses, handshake WS, wrap into RawConnection.
    """

    def __init__(self, handler: THandler) -> None:
        self._handler = handler
        self._server = None

    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        addr_str = str(maddr)
        if addr_str.endswith("/wss"):
            raise NotImplementedError("/wss (TLS) not yet supported")

        host = (
            maddr.value_for_protocol("ip4")
            or maddr.value_for_protocol("ip6")
            or maddr.value_for_protocol("dns")
            or maddr.value_for_protocol("dns4")
            or maddr.value_for_protocol("dns6")
            or "0.0.0.0"
        )
        port = int(maddr.value_for_protocol("tcp"))

        async def serve(
            task_status: TaskStatus[Any] = trio.TASK_STATUS_IGNORED,
        ) -> None:
            # positional ssl_context=None
            self._server = await serve_websocket(
                self._handle_connection, host, port, None
            )
            task_status.started()
            await self._server.wait_closed()

        await nursery.start(serve)
        return True

    async def _handle_connection(self, websocket: Any) -> None:
        try:
            # use raw transport_stream
            conn = P2PWebSocketConnection(websocket.stream)
            raw = RawConnection(conn, initiator=False)
            await self._handler(raw)
        except Exception as e:
            logger.debug("WebSocket connection error: %s", e)

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        if not self._server or not self._server.sockets:
            return ()
        addrs = []
        for sock in self._server.sockets:
            host, port = sock.getsockname()[:2]
            if sock.family == socket.AF_INET6:
                addr = Multiaddr(f"/ip6/{host}/tcp/{port}/ws")
            else:
                addr = Multiaddr(f"/ip4/{host}/tcp/{port}/ws")
            addrs.append(addr)
        return tuple(addrs)

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
