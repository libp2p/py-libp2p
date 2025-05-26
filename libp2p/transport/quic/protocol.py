from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
)

from aioquic.quic.connection import (
    QuicConnection,
)

from libp2p.abc import (
    IRawConnection,
)

if TYPE_CHECKING:
    from libp2p.transport.quic.transport import (
        QuicTransport,
    )


class Libp2pQuicProtocol(IRawConnection):
    def __init__(self, transport: "QuicTransport") -> None:
        self._transport = transport
        self._remote_address: Optional[tuple[str, int]] = None
        self._connected: bool = False

    def get_remote_address(self) -> Optional[tuple[str, int]]:
        return self._remote_address

    def is_connected(self) -> bool:
        return self._connected

    async def run(self) -> None:
        # Set _connected to True when the connection is established
        self._connected = True
        print("Protocol run started, connection established")  # Add logging
        # Your actual logic goes here

    def some_method(self) -> None:
        # Lazy import to avoid circular dependency
        pass

        print("Using QuicTransport")
        # Use QuicTransport here

    def quic_event_received(self, event: Any) -> None:
        # Placeholder for handling QUIC events
        print("QUIC event received:", event)

    # Define _connection attribute
    _connection: Optional[QuicConnection] = None

    async def read(self, n: int = -1) -> bytes:
        raise NotImplementedError("QUIC read not implemented yet")

    async def write(self, data: bytes) -> None:
        raise NotImplementedError("QUIC write not implemented yet")

    async def close(self) -> None:
        raise NotImplementedError("QUIC close not implemented yet")
