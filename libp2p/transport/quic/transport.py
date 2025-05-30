import datetime
import ssl
import time
from typing import (
    Optional,
)

from aioquic.quic.configuration import (
    QuicConfiguration,
)
from aioquic.quic.connection import (
    QuicConnection,
)
from aioquic.tls import (
    CipherSuite,
    SessionTicket,
)
from cryptography import (
    x509,
)
from cryptography.hazmat.primitives import (
    hashes,
    serialization,
)
from cryptography.hazmat.primitives.asymmetric import (
    ec,
)
from cryptography.x509.oid import (
    NameOID,
)
from multiaddr import (
    Multiaddr,
)
import trio
from trio import (
    Nursery,
)
from trio.socket import (
    SocketType,
)

from libp2p.abc import (
    IListener,
    IRawConnection,
    ITransport,
)
from libp2p.custom_types import (
    THandler,
)
from libp2p.transport.exceptions import (
    TransportError,
)

from .protocol import (
    Libp2pQuicProtocol,
)


class QuicListener(IListener):
    def __init__(self, transport: "QuicTransport", handler_function: THandler):
        self.transport = transport
        self.handler_function = handler_function
        self._nursery: Optional[Nursery] = None
        self._running = True

    async def listen(self, maddr: Multiaddr, nursery: Nursery) -> bool:
        try:
            host = maddr.value_for_protocol(4)  # IPv4
            port = int(maddr.value_for_protocol("udp"))

            self.transport.host = host
            self.transport.port = port
            self._nursery = nursery

            await self.transport.listen()
            self._nursery.start_soon(self._handle_connections)

            return True
        except Exception as e:
            raise TransportError(f"Failed to start listening: {e}") from e

    async def _handle_connections(self) -> None:
        if not self._nursery or not self.transport._server:
            return

        while self._running:
            try:
                data, addr = await self.transport._server.recvfrom(1200)
                print(f"Received datagram of size {len(data)} bytes from {addr}")

                connection = self.transport.connections.get(addr)
                if connection is None:
                    try:
                        connection = QuicConnection(
                            configuration=self.transport.config,
                            session_ticket_handler=(
                                self.transport._handle_session_ticket
                            ),
                            original_destination_connection_id=b"\x00" * 8,
                        )
                        print(f"Created new connection for {addr}")

                        protocol = self.transport._create_protocol()
                        protocol._connection = connection
                        protocol._remote_address = addr

                        self.transport.connections[addr] = connection

                        connection.receive_datagram(data, addr, time.time())

                        self._nursery.start_soon(self._run_protocol, protocol, addr)
                        self._nursery.start_soon(self._run_handler, protocol)

                    except Exception as e:
                        print(f"Error creating new connection: {e}")
                        import traceback

                        traceback.print_exc()
                        continue

                try:
                    connection.receive_datagram(data, addr, time.time())
                    print(f"Processed datagram from {addr}")
                except Exception as e:
                    print(f"Error processing data: {e}")
                    import traceback

                    traceback.print_exc()

            except Exception as e:
                print(f"Error in connection handler: {e}")
                import traceback

                traceback.print_exc()
                await trio.sleep(0.1)

    async def _run_protocol(
        self, protocol: "Libp2pQuicProtocol", addr: tuple[str, int]
    ) -> None:
        try:
            while protocol.is_connected():
                try:
                    datagrams = protocol._connection.datagrams_to_send(time.time())
                    for data, _ in datagrams:
                        if len(data) > 1200:
                            print(
                                f"Warning: Truncating oversized datagram from :"
                                f"{len(data)} to 1200 bytes"
                            )
                            data = data[:1200]
                        await self.transport._server.sendto(data, addr)

                    while True:
                        event = protocol._connection.next_event()
                        if event is None:
                            break
                        protocol.quic_event_received(event)

                    await trio.sleep(0.01)
                except Exception as e:
                    print(f"Error in protocol loop: {e}")
                    import traceback

                    traceback.print_exc()
                    await trio.sleep(0.1)
        except Exception as e:
            print(f"Error in protocol event loop: {e}")
            import traceback

            traceback.print_exc()

    async def _run_handler(self, protocol: "Libp2pQuicProtocol") -> None:
        try:
            await self.handler_function(protocol)
        except Exception as e:
            print(f"Error in handler function: {e}")
            import traceback

            traceback.print_exc()

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        if not self.transport._server:
            return ()
        addr = self.transport._server.getsockname()
        return (Multiaddr(f"/ip4/{addr[0]}/udp/{addr[1]}/quic"),)

    async def close(self) -> None:
        self._running = False
        self._nursery = None
        await self.transport.close()


class QuicTransport(ITransport):
    def __init__(
        self, host: str = "0.0.0.0", port: int = 0, handshake_timeout: float = 10.0
    ):
        self.host = host
        self.port = port
        self.connections: dict[tuple[str, int], QuicConnection] = {}
        self._server: Optional[SocketType] = None
        self.handshake_timeout = handshake_timeout

        # Generate ephemeral key pair
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.public_key = self.private_key.public_key()

        # Create a self-signed X.509 certificate
        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
            ]
        )
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(self.public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName("localhost")]),
                critical=False,
            )
            .sign(self.private_key, hashes.SHA256())
        )

        # Save the certificate and key to files
        with open("cert.pem", "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        with open("key.pem", "wb") as f:
            f.write(
                self.private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        # Create SSL context
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")
        context.set_alpn_protocols(["h3"])  # or your specific protocol
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_3

        # Adjust handshake timeout
        self.handshake_timeout = 20.0  # Increase timeout to 20 seconds

        # Use the context in QuicConfiguration
        self.config = QuicConfiguration(
            is_client=False,
            alpn_protocols=["libp2p-quic"],
            verify_mode=ssl.CERT_REQUIRED,
            max_datagram_size=1200,
            certificate=cert.public_bytes(serialization.Encoding.PEM),
            private_key=self.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ),
            cipher_suites=[
                CipherSuite.AES_128_GCM_SHA256,
                CipherSuite.AES_256_GCM_SHA384,
                CipherSuite.CHACHA20_POLY1305_SHA256,
            ],
        )

        def verify_certificate(
            certificates: list[x509.Certificate], context: ssl.SSLContext
        ) -> None:
            # Extract and verify the libp2p extension
            # Compute the Peer ID and validate
            # Abort on failure, store Peer ID on success
            pass

        print(context.get_ciphers())

        # Add logging to verify configuration
        print(f"QUIC Transport initialized with host: {self.host}, port: {self.port}")

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        if not self._server:
            return ()
        addr = self._server.getsockname()
        return (Multiaddr(f"/ip4/{addr[0]}/udp/{addr[1]}/quic"),)

    def create_listener(self, handler_function: THandler) -> IListener:
        return QuicListener(self, handler_function)

    async def listen(self) -> None:
        try:
            self._server = trio.socket.socket(
                trio.socket.AF_INET, trio.socket.SOCK_DGRAM
            )
            await self._server.bind((self.host, self.port))
            self.port = self._server.getsockname()[1]
            print(f"Listening on {self.host}:{self.port}")  # Add logging
        except Exception as e:
            raise TransportError(f"Failed to start QUIC server: {e}") from e

    def _create_protocol(self) -> Libp2pQuicProtocol:
        # Implement the protocol creation logic here
        protocol = Libp2pQuicProtocol(self)
        protocol._connection = None  # Initialize _connection
        return protocol

    async def dial(self, maddr: Multiaddr) -> IRawConnection:
        try:
            host = maddr.value_for_protocol(4)  # IPv4
            port = int(maddr.value_for_protocol("udp"))

            client_config = QuicConfiguration(
                is_client=True,
                alpn_protocols=["libp2p-quic"],
                verify_mode=None,
                max_datagram_size=1200,
                server_name=host,
                cipher_suites=[
                    CipherSuite.AES_128_GCM_SHA256,
                    CipherSuite.AES_256_GCM_SHA384,
                    CipherSuite.CHACHA20_POLY1305_SHA256,
                ],
            )

            connection = QuicConnection(
                configuration=client_config,
                session_ticket_handler=self._handle_session_ticket,
            )

            protocol = self._create_protocol()
            protocol._connection = connection
            protocol._remote_address = (host, port)

            connection.connect((host, port), now=time.time())
            print(f"Attempting to connect to {host}:{port}")

            sock = trio.socket.socket(trio.socket.AF_INET, trio.socket.SOCK_DGRAM)
            await sock.connect((host, port))

            with trio.move_on_after(self.handshake_timeout):
                while True:
                    datagrams = connection.datagrams_to_send(time.time())
                    for data, _ in datagrams:
                        if len(data) > 1200:
                            print(
                                f"Warning: Truncating oversized datagram from :"
                                f"{len(data)} to 1200 bytes"
                            )
                            data = data[:1200]
                        await sock.send(data)
                        print(
                            f"Sent datagram of size {len(data)} bytes to {host}:{port}"
                        )

                    try:
                        data = await sock.recv(1200)
                        print(f"Received datagram of size {len(data)} bytes")
                        connection.receive_datagram(data, (host, port), time.time())
                    except BlockingIOError:
                        pass

                    while True:
                        event = connection.next_event()
                        if event is None:
                            break
                        print(f"Processing QUIC event: {event}")
                        protocol.quic_event_received(event)

                    await trio.sleep(0.01)

            # if not protocol.is_connected():
            #     print("QUIC handshake timed out")
            #     raise TransportError("QUIC handshake timed out")

            async with trio.open_nursery() as nursery:
                nursery.start_soon(protocol.run)

            return protocol

        except Exception as e:
            print(f"Failed to dial peer: {e}")
            import traceback

            traceback.print_exc()
            raise TransportError(f"Failed to dial peer: {e}") from e

    def _handle_session_ticket(self, ticket: SessionTicket) -> None:
        # TODO: Implement session ticket handling
        pass

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


class QuicStream(IRawConnection):
    def __init__(self, stream_id: int, protocol: "Libp2pQuicProtocol"):
        self.stream_id = stream_id
        self.protocol = protocol
        self._buffer = bytearray()
        self._data_event = trio.Event()

    async def write(self, data: bytes) -> None:
        if not self.protocol._connection:
            raise TransportError("No active connection")
        self.protocol._connection.send_stream_data(self.stream_id, data)

    async def read(self, n: int = None) -> bytes:
        while not self._buffer:
            await self._data_event.wait()
            self._data_event = trio.Event()
        if n is None:
            n = len(self._buffer)
        data = self._buffer[:n]
        self._buffer = self._buffer[n:]
        return bytes(data)

    def _receive_data(self, data: bytes) -> None:
        """Receive data and add it to the buffer."""
        self._buffer.extend(data)
        self._data_event.set()
        return None

    async def close(self) -> None:
        """Close the stream."""
        if self.protocol._connection:
            self.protocol._connection.send_stream_data(
                self.stream_id, b"", end_stream=True
            )

    def get_remote_address(self) -> Optional[tuple[str, int]]:
        """Get the remote address of the connected peer."""
        return self.protocol.get_remote_address()


__all__ = [
    "QuicTransport",
]
