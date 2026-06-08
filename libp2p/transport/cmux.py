from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
from typing import TYPE_CHECKING, Any

from multiaddr import Multiaddr
import trio
from trio_websocket._impl import wrap_server_stream

from libp2p.abc import IListener
from libp2p.custom_types import THandler
from libp2p.io.peekable_stream import PeekableStream
from libp2p.io.trio import TrioTCPStream
from libp2p.transport.exceptions import OpenConnectionError

if TYPE_CHECKING:
    from trio_websocket import WebSocketRequest

logger = logging.getLogger(__name__)


class SharedTCPDispatcher(IListener):
    """
    A single TCP listener that acts as a Connection Multiplexer (cmux).

    It peeks at the first bytes of an incoming connection:
    - If it starts with an HTTP method (GET, POST, PUT), it routes to WebSocket.
    - Otherwise, it routes to raw TCP.
    """

    host: str
    port: int
    tcp_handler: THandler | None
    ws_handler: Callable[[WebSocketRequest], Awaitable[None]] | None
    listen_maddr: Multiaddr | None

    _nursery: trio.Nursery | None
    _started: trio.Event
    _stopped: trio.Event
    _closed: bool
    _start_error: BaseException | None

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.tcp_handler = None
        self.ws_handler = None

        self._nursery = None
        self._started = trio.Event()
        self._stopped = trio.Event()
        self._closed = False
        self._start_error = None
        self.listen_maddr = None

    async def listen(self, maddr: Multiaddr) -> None:
        """
        Starts the shared TCP server. Subsequent calls for the same port
        just return if it's already running.
        """
        if self._started.is_set():
            return

        async def serve_tcp(task_status: Any = trio.TASK_STATUS_IGNORED) -> None:
            logger.debug(f"SharedTCPDispatcher serving on {self.host}:{self.port}")
            try:
                await trio.serve_tcp(
                    self._handle_stream,
                    self.port,
                    host=self.host,
                    task_status=task_status,
                )
            except Exception as e:
                logger.error(f"SharedTCPDispatcher serve error: {e}")
                raise

        async def _run_server() -> None:
            try:
                async with trio.open_nursery() as nursery:
                    self._nursery = nursery
                    try:
                        await nursery.start(serve_tcp)
                    except BaseException as error:
                        self._start_error = error
                    finally:
                        self._started.set()
            finally:
                self._stopped.set()
                self._nursery = None

        trio.lowlevel.spawn_system_task(_run_server)
        await self._started.wait()

        if self._start_error is not None:
            raise OpenConnectionError(
                f"CMUX Failed to listen on {maddr}: {self._start_error}"
            )

    async def _handle_stream(self, stream: trio.SocketStream) -> None:
        """
        Peek at the first bytes. If it looks like HTTP, route to WS handler.
        Otherwise, route to TCP handler.
        """
        try:
            peekable = PeekableStream(stream)
            try:
                with trio.fail_after(2.0):
                    data = await peekable.receive_some(8)
            except trio.TooSlowError:
                data = b""

            # Prepend the read data back to the buffer for the actual handler
            peekable.buffer = bytearray(data) + peekable.buffer

            is_http = (
                data.startswith(b"GET ")
                or data.startswith(b"POST ")
                or data.startswith(b"PUT ")
            )

            if is_http and self.ws_handler is not None:
                if self._nursery is None:
                    return
                # wrap_server_stream requires a nursery
                ws_request = await wrap_server_stream(self._nursery, peekable)
                await self.ws_handler(ws_request)
            elif not is_http and self.tcp_handler is not None:
                tcp_stream = TrioTCPStream(peekable)
                await self.tcp_handler(tcp_stream)
            else:
                await stream.aclose()
        except Exception:
            try:
                await stream.aclose()
            except Exception:
                pass

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """Return the multiaddresses this listener is bound to."""
        if self.listen_maddr is not None:
            return (self.listen_maddr,)
        return ()

    async def close(self) -> None:
        """Close the listener and its background nursery."""
        if self._closed:
            return
        self._closed = True
        if self._nursery is not None:
            self._nursery.cancel_scope.cancel()
        if self._started.is_set():
            await self._stopped.wait()
