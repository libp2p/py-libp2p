from typing import (
    Any,
    AsyncIterator,
    Optional,
    Tuple,
)

<<<<<<< HEAD
from multiaddr import Multiaddr
from libp2p.peer.id import ID
from libp2p.transport.transport_interface import ITransport
from libp2p.transport.listener_interface import IListener
from libp2p.network.stream.net_stream_interface import INetStream
=======
from aioquic.asyncio import (
    QuicServer,
    serve,
)
from aioquic.quic.configuration import (
    QuicConfiguration,
)
from multiaddr import (
    Multiaddr,
)
from trio import (
    Nursery,
)
>>>>>>> fabebacf046c4b67ee2e03beafaa89fc4b1cc384

from libp2p.network.stream.net_stream_interface import (
    INetStream,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.transport.listener_interface import (
    IListener,
)
from libp2p.transport.transport import (
    Transport,
)

from .quic import (
    QuicProtocol,
)


class QuicTransport(Transport):
    def __init__(self, configuration: Optional[QuicConfiguration] = None):
        self.configuration = configuration or QuicConfiguration(is_client=True)

    async def dial(self, peer_id: ID, multiaddr: Multiaddr) -> INetStream:
        host, port = self._parse_multiaddr(multiaddr)
        protocol = QuicProtocol(host, port, self.configuration)
        await protocol.run()
        return protocol  # Return the protocol as a stream

    async def listen(self, multiaddr: Multiaddr) -> IListener:
        host, port = self._parse_multiaddr(multiaddr)
        listener = QuicListener(self.configuration, host, port)
        await listener.start()
        return listener

    def _parse_multiaddr(self, multiaddr: Multiaddr) -> Tuple[str, int]:
        parts = multiaddr.split("/")
        if parts[1] != "ip4" and parts[1] != "ip6":
            raise ValueError("Only IPv4 and IPv6 addresses are supported")
        host = parts[2]
        port = int(parts[4])
        return host, port


class QuicListener(IListener):
    def __init__(self, configuration: QuicConfiguration, host: str, port: int):
        self.configuration = configuration
        self.host = host
        self.port = port
        self.server: Optional[QuicServer] = None  # Explicitly type as Optional

    async def start(self) -> None:
        self.server = await serve(
            self.host,
            self.port,
            configuration=self.configuration,
            create_protocol=QuicProtocol,
        )

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def close(self) -> None:
        """Closes the listener."""
        await self.stop()

    async def listen(self, maddr: Any, nursery: Nursery) -> bool:
        """Start listening for incoming QUIC connections."""
        await self.start()
        return True  # Indicate that listening started successfully

    def get_addrs(self) -> AsyncIterator[Multiaddr]:
        yield Multiaddr(f"/ip4/{self.host}/udp/{self.port}/quic")
