import asyncio
import time
from typing import (
    Optional,
)

from aioquic.asyncio import (
    QuicConnectionProtocol,
)
from aioquic.quic.configuration import (
    QuicConfiguration,
)
from aioquic.quic.connection import (
    QuicConnection,
)
from aioquic.quic.events import (
    QuicEvent,
    StreamDataReceived,
)
from aioquic.tls import (
    SessionTicket,
)
from multiaddr import (
    Multiaddr,
)
from trio import (
    Nursery,
)

from libp2p.abc import (
    IListener,
    IRawConnection,
    ITransport,
)
from libp2p.custom_types import (
    THandler,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.transport.exceptions import (
    TransportError,
)


class QuicListener(IListener):
    def __init__(self, transport: "QuicTransport", handler_function: THandler):
        self.transport = transport
        self.handler_function = handler_function

    async def listen(self, maddr: Multiaddr, nursery: Nursery) -> bool:
        """Start listening on the given multiaddr."""
        try:
            # Extract host and port from multiaddr
            host = maddr.value_for_protocol(4)  # IPv4
            port = int(maddr.value_for_protocol(17))  # UDP

            # Update transport settings
            self.transport.host = host
            self.transport.port = port

            # Start listening
            await self.transport.listen()
            return True
        except Exception as e:
            raise TransportError(f"Failed to start listening: {e}") from e

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """Get the listening addresses."""
        if not self.transport._server:
            return ()
        socket = self.transport._server.get_extra_info("socket")
        addr = socket.getsockname()
        return (Multiaddr(f"/ip4/{addr[0]}/udp/{addr[1]}/quic"),)

    async def close(self) -> None:
        """Close the listener."""
        await self.transport.close()


class QuicTransport(ITransport):
    def __init__(self, host: str = "0.0.0.0", port: int = 0):
        self.host = host
        self.port = port
        self.connections: dict[ID, QuicConnection] = {}
        self._server: Optional[asyncio.DatagramTransport] = None

        # QUIC configuration
        self.config = QuicConfiguration(
            is_client=False,
            alpn_protocols=["libp2p-quic"],
            verify_mode=None,  # TODO: Implement proper certificate verification
        )

    def create_listener(self, handler_function: THandler) -> IListener:
        """Create a new QUIC listener."""
        return QuicListener(self, handler_function)

    async def listen(self) -> None:
        """Start listening for QUIC connections."""
        try:
            # Create a UDP endpoint
            loop = asyncio.get_event_loop()
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: self._create_protocol(), local_addr=(self.host, self.port)
            )

            # Store the transport and protocol
            self._server = transport
            self.port = transport.get_extra_info("socket").getsockname()[1]

        except Exception as e:
            raise TransportError(f"Failed to start QUIC server: {e}") from e

    def _create_protocol(self) -> QuicConnectionProtocol:
        """Create a new QUIC protocol instance."""
        return Libp2pQuicProtocol(self)

    async def dial(self, maddr: Multiaddr) -> IRawConnection:
        """Dial a peer using QUIC."""
        try:
            # Extract host and port from multiaddr
            host = maddr.value_for_protocol(4)  # IPv4
            port = int(maddr.value_for_protocol(17))  # UDP

            # Create client configuration
            client_config = QuicConfiguration(
                is_client=True,
                alpn_protocols=["libp2p-quic"],
                verify_mode=None,  # TODO: Implement proper certificate verification
            )

            # Create connection
            connection = QuicConnection(
                configuration=client_config,
                session_ticket_handler=self._handle_session_ticket,
            )

            # Connect to peer
            connection.connect((host, port), now=time.time())

            # Create protocol
            protocol = Libp2pQuicProtocol(self)
            protocol._connection = connection  # Use protected attribute

            # Store connection
            self.connections[protocol.peer_id] = connection

            return protocol

        except Exception as e:
            raise TransportError(f"Failed to dial peer: {e}") from e

    def _handle_session_ticket(self, ticket: SessionTicket) -> None:
        """Handle session ticket for connection resumption."""
        # TODO: Implement session ticket handling

    async def close(self) -> None:
        """Close all connections and stop listening."""
        # Close all connections
        for connection in self.connections.values():
            connection.close()
        self.connections.clear()

        # Stop server if running
        if self._server:
            self._server.close()
            self._server = None


class Libp2pQuicProtocol(QuicConnectionProtocol, IRawConnection):
    def __init__(self, transport: QuicTransport):
        # Create QUIC configuration for the protocol
        quic = QuicConnection(
            configuration=QuicConfiguration(
                is_client=True,
                alpn_protocols=["libp2p-quic"],
                verify_mode=None,
            )
        )
        super().__init__(quic=quic, stream_handler=None)
        self.transport = transport
        self._connection: Optional[QuicConnection] = None
        self._peer_id: Optional[ID] = None
        self._remote_address: Optional[tuple[str, int]] = None

    @property
    def connection(self) -> Optional[QuicConnection]:
        """Get the QUIC connection."""
        return self._connection

    @property
    def peer_id(self) -> ID:
        """Get the peer ID."""
        if not self._peer_id:
            # TODO: Generate peer ID from connection certificate
            self._peer_id = ID(b"peer_id")  # Placeholder
        return self._peer_id

    def get_remote_address(self) -> Optional[tuple[str, int]]:
        """Get the remote address of the connected peer."""
        if not self._remote_address and self._connection:
            try:
                # Use the correct method to retrieve the remote address
                self._remote_address = self._connection._network_paths[0].addr
            except Exception as e:
                # Handle any exceptions that might occur
                print(f"Error getting remote address: {e}")
        return self._remote_address

    async def read(self, n: Optional[int] = None) -> bytes:
        """Read data from the connection."""
        # TODO: Implement read using QUIC streams
        raise NotImplementedError("Read not implemented yet")

    async def write(self, data: bytes) -> None:
        """Write data to the connection."""
        # TODO: Implement write using QUIC streams
        raise NotImplementedError("Write not implemented yet")

    def quic_event_received(self, event: QuicEvent) -> None:
        """Handle QUIC events."""
        if isinstance(event, StreamDataReceived):
            # TODO: Handle incoming stream data
            pass

    async def stream_data_received(self, stream_id: int, data: bytes) -> None:
        """Handle incoming stream data."""
        # TODO: Implement stream data handling
