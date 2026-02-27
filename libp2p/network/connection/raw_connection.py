from multiaddr import (
    Multiaddr,
)

from libp2p.abc import (
    ConnectionType,
    IRawConnection,
)
from libp2p.io.abc import (
    ReadWriteCloser,
)
from libp2p.io.exceptions import (
    IOException,
)

from .exceptions import (
    RawConnError,
)


class RawConnection(IRawConnection):
    stream: ReadWriteCloser
    is_initiator: bool
    _connection_type: ConnectionType
    _actual_addresses: list[Multiaddr] | None

    def __init__(
        self,
        stream: ReadWriteCloser,
        initiator: bool,
        connection_type: ConnectionType = ConnectionType.DIRECT,
        addresses: list[Multiaddr] | None = None,
    ) -> None:
        self.stream = stream
        self.is_initiator = initiator
        self._connection_type = connection_type
        self._actual_addresses = addresses

    async def write(self, data: bytes) -> None:
        """Raise `RawConnError` if the underlying connection breaks."""
        try:
            await self.stream.write(data)
        except (IOException, ConnectionResetError) as error:
            raise RawConnError from error

    async def read(self, n: int | None = None) -> bytes:
        """
        Read up to ``n`` bytes from the underlying stream. This call is
        delegated directly to the underlying ``self.reader``.

        Raise `RawConnError` if the underlying connection breaks
        """
        try:
            return await self.stream.read(n)
        except (IOException, ConnectionResetError) as error:
            raise RawConnError from error

    async def close(self) -> None:
        await self.stream.close()

    def get_remote_address(self) -> tuple[str, int] | None:
        """Delegate to the underlying stream's get_remote_address method."""
        return self.stream.get_remote_address()

    def get_transport_addresses(self) -> list[Multiaddr]:
        """
        Get the actual transport addresses used by this connection.

        Returns the real IP/port addresses, not peerstore addresses.
        For relayed connections, should include /p2p-circuit in the path.
        """
        if self._actual_addresses is not None:
            return self._actual_addresses

        remote_addr = self.get_remote_address()
        if remote_addr is None:
            return []
        ip, port = remote_addr
        # Create multiaddr from IP and port
        # Note: This defaults to TCP as protocol. For proper protocol detection,
        # transport-specific implementations should provide addresses via constructor.
        try:
            # Detect protocol from connection type or default to TCP
            # In practice, only TCP connections use RawConnection directly;
            # other protocols (QUIC) have dedicated implementations
            protocol = "tcp"

            # Try to infer IPv4 vs IPv6
            if ":" in ip:
                addr = Multiaddr(f"/ip6/{ip}/{protocol}/{port}")
            else:
                addr = Multiaddr(f"/ip4/{ip}/{protocol}/{port}")
            return [addr]
        except Exception:
            return []

    def get_connection_type(self) -> ConnectionType:
        """
        Get the type of connection (direct, relayed, etc.)
        """
        return self._connection_type
