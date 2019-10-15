import asyncio
from typing import Any, Dict, List, Tuple

from multiaddr import Multiaddr

import asyncio_dgram
from asyncio_dgram.aio import DatagramStream
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.listener_interface import IListener
from libp2p.transport.stream_interface import IStreamReader, IStreamWriter
from libp2p.transport.transport_interface import ITransport
from libp2p.transport.typing import THandler
from libp2p.transport.udp.udp_stream import (
    UDPServerStreamReader,
    UDPServerStreamWriter,
    UDPStreamReader,
    UDPStreamWriter,
)


async def open_datagram_connection(
    host: str, port: int
) -> Tuple[IStreamReader, IStreamWriter]:
    stream = await asyncio_dgram.connect((host, port))
    reader, writer = UDPStreamReader(stream), UDPStreamWriter(stream)
    return reader, writer


def start_udp_server(handler: THandler, host: str, port: int) -> "UDPServer":
    server = UDPServer(handler, host, port)
    asyncio.create_task(server.listen())
    return server


class UDPServer:
    _host: str
    _port: int
    _stream: DatagramStream
    _handler_queues: Dict[Any, asyncio.Queue[bytes]]
    _running_handlers: List[asyncio.Task[Any]]

    def __init__(self, handler: THandler, host: str, port: int):
        _handler: THandler  # in class-level, MyPy raises error, because it treats like a method
        self._handler = handler
        self._host = host
        self._port = port
        self._handler_queues = {}
        self._running_handlers = []

    async def listen(self) -> None:
        self._stream = await asyncio_dgram.bind((self._host, self._port))
        while True:
            data, addr = await self._stream.recv()
            await self._deliver_data(addr, data)

    async def close(self) -> None:
        self._stream.close()
        # TODO: Correct way to destroy all handlers?
        for task in self._running_handlers:
            task.cancel()
        await asyncio.gather(task for task in self._running_handlers)

    def get_extra_info(self, field: str) -> Any:
        return self._stream.__getattribute__(
            field
        )  # it is compatible with some TCP fields

    def close_handler_stream(self, addr: Any) -> None:
        """
        Method called just by Streams used by handlers
        :param addr: socket address is connected to
        :return:
        """
        if addr in self._running_handlers:
            del self._running_handlers[addr]

    async def _deliver_data(self, addr: Any, data: bytes) -> None:
        if addr in self._handler_queues:
            await self._handler_queues[addr].put(data)
        else:
            queue = await self._init_and_get_new_queue(addr, data)
            reader, writer = (
                UDPServerStreamReader(self._stream, self, addr, queue),
                UDPServerStreamWriter(self._stream, self, addr),
            )
            await self._handler(reader, writer)

    async def _init_and_get_new_queue(
        self, addr: Any, data: bytes
    ) -> asyncio.Queue[bytes]:
        queue: asyncio.Queue[bytes]
        queue = asyncio.Queue()
        self._handler_queues[addr] = queue
        await queue.put(data)
        return queue


class UDPListener(IListener):
    multiaddrs: List[Multiaddr]
    server = None

    def __init__(self, handler_function: THandler) -> None:
        self.multiaddrs = []
        self.server = None
        self.handler = handler_function

    async def listen(self, maddr: Multiaddr) -> bool:
        """
        put listener in listening mode and wait for incoming connections
        :param maddr: maddr of peer
        :return: return True if successful
        """
        self.server = start_udp_server(
            self.handler,
            maddr.value_for_protocol("ip4"),
            maddr.value_for_protocol("udp"),
        )
        self.multiaddrs.append(
            _multiaddr_from_socketname(self.server.get_extra_info("sockname"))
        )
        return True

    def get_addrs(self) -> List[Multiaddr]:
        """
        retrieve list of addresses the listener is listening on
        :return: return list of addrs
        """
        # TODO check if server is listening
        return self.multiaddrs

    async def close(self) -> None:
        """
        close the listener such that no more connections
        can be open on this transport instance
        """
        if self.server is None:
            return
        await self.server.close()
        self.server = None


class UDP(ITransport):
    async def dial(self, maddr: Multiaddr) -> IRawConnection:
        """
        dial a transport to peer listening on multiaddr
        :param maddr: multiaddr of peer
        :return: `RawConnection` if successful
        :raise OpenConnectionError: raised when failed to open connection
        """
        self.host = maddr.value_for_protocol("ip4")
        self.port = int(maddr.value_for_protocol("tcp"))

        try:
            reader, writer = await open_datagram_connection(self.host, self.port)
        except (ConnectionAbortedError, ConnectionRefusedError) as error:
            raise OpenConnectionError(error)

        return RawConnection(reader, writer, True)

    def create_listener(self, handler_function: THandler) -> UDPListener:
        """
        create listener on transport
        :param handler_function: a function called when a new connection is received
        that takes a connection as argument which implements interface-connection
        :return: a listener object that implements listener_interface.py
        """
        return UDPListener(handler_function)


def _multiaddr_from_socketname(socketname: Tuple[str, int]) -> Multiaddr:
    return Multiaddr(f"/ip4/{socketname[0]}/udp/{socketname[1]}")
