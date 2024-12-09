
import asyncio
from aioquic.asyncio import connect, serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from libp2p.transport.typing import TTransport

class QuicTransport(TTransport):
    def __init__(self, local_peer, security_protocol=None):
        self.local_peer = local_peer
        self.security_protocol = security_protocol
        self.connections = []

    async def dial(self, peer_id, multiaddr):
        """
        Dial a peer using the given multiaddr.
        """
        host, port = self.parse_multiaddr(multiaddr)
        config = QuicConfiguration(is_client=True)
        protocol = QuicConnectionProtocol(config)
        quic_conn = await connect(host, port, configuration=config, create_protocol=protocol)
        self.connections.append(quic_conn)
        return quic_conn

    async def listen(self, multiaddr):
        """
        Listen for incoming QUIC connections.
        """
        host, port = self.parse_multiaddr(multiaddr)
        config = QuicConfiguration(is_client=False)
        server = await serve(host, port, configuration=config, create_protocol=self._on_new_connection)
        return server

    def _on_new_connection(self, protocol):
        """
        Handle a new incoming connection.
        """
        self.connections.append(protocol)
        print("New connection established:", protocol)

    @staticmethod
    def parse_multiaddr(multiaddr):
        """
        Parse multiaddr to host and port.
        """
        components = multiaddr.split("/")
        return components[-2], int(components[-1])
