import logging

import pytest
import trio
from trio.testing import (
    memory_stream_pair,
)

from libp2p.abc import IRawConnection
from libp2p.crypto.ed25519 import (
    create_new_key_pair,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.security.insecure.transport import (
    InsecureTransport,
)
from libp2p.stream_muxer.yamux.yamux import (
    Yamux,
    YamuxStream,
)


class TrioStreamAdapter(IRawConnection):
    """Adapter to make trio memory streams work with libp2p."""

    def __init__(self, send_stream, receive_stream, is_initiator=False):
        self.send_stream = send_stream
        self.receive_stream = receive_stream
        self.is_initiator = is_initiator

    async def write(self, data: bytes) -> None:
        logging.debug(f"Attempting to write {len(data)} bytes")
        with trio.move_on_after(2):
            await self.send_stream.send_all(data)

    async def read(self, n: int | None = None) -> bytes:
        if n is None or n <= 0:
            raise ValueError("Reading unbounded or zero bytes not supported")
        logging.debug(f"Attempting to read {n} bytes")
        with trio.move_on_after(2):
            data = await self.receive_stream.receive_some(n)
            logging.debug(f"Read {len(data)} bytes")
            return data

    async def close(self) -> None:
        logging.debug("Closing stream")
        await self.send_stream.aclose()
        await self.receive_stream.aclose()

    def get_remote_address(self) -> tuple[str, int] | None:
        """Return None since this is a test adapter without real network info."""
        return None


@pytest.fixture
def key_pair():
    return create_new_key_pair()


@pytest.fixture
def peer_id(key_pair):
    return ID.from_pubkey(key_pair.public_key)


@pytest.fixture
async def secure_conn_pair(key_pair, peer_id):
    """Create a pair of secure connections for testing."""
    logging.debug("Setting up secure_conn_pair")
    client_send, server_receive = memory_stream_pair()
    server_send, client_receive = memory_stream_pair()

    client_rw = TrioStreamAdapter(client_send, client_receive)
    server_rw = TrioStreamAdapter(server_send, server_receive)

    insecure_transport = InsecureTransport(key_pair)

    async def run_outbound(nursery_results):
        with trio.move_on_after(5):
            client_conn = await insecure_transport.secure_outbound(client_rw, peer_id)
            logging.debug("Outbound handshake complete")
            nursery_results["client"] = client_conn

    async def run_inbound(nursery_results):
        with trio.move_on_after(5):
            server_conn = await insecure_transport.secure_inbound(server_rw)
            logging.debug("Inbound handshake complete")
            nursery_results["server"] = server_conn

    nursery_results = {}
    async with trio.open_nursery() as nursery:
        nursery.start_soon(run_outbound, nursery_results)
        nursery.start_soon(run_inbound, nursery_results)
        await trio.sleep(0.1)  # Give tasks a chance to finish

    client_conn = nursery_results.get("client")
    server_conn = nursery_results.get("server")

    if client_conn is None or server_conn is None:
        raise RuntimeError("Handshake failed: client_conn or server_conn is None")

    logging.debug("secure_conn_pair setup complete")
    return client_conn, server_conn


@pytest.fixture
async def yamux_pair(secure_conn_pair, peer_id):
    """Create a pair of Yamux multiplexers for testing."""
    logging.debug("Setting up yamux_pair")
    client_conn, server_conn = secure_conn_pair
    client_yamux = Yamux(client_conn, peer_id, is_initiator=True)
    server_yamux = Yamux(server_conn, peer_id, is_initiator=False)
    async with trio.open_nursery() as nursery:
        with trio.move_on_after(5):
            nursery.start_soon(client_yamux.start)
            nursery.start_soon(server_yamux.start)
            await trio.sleep(0.1)
            logging.debug("yamux_pair started")
        yield client_yamux, server_yamux
    logging.debug("yamux_pair cleanup")


@pytest.mark.trio
async def test_yamux_race_condition_without_locks(yamux_pair):
    """
    Test for race-around/interleaving in Yamux streams,when reading in
    segments of data.
    This launches concurrent writers/readers on both sides of a stream.
    If there is no proper locking, the received data may be interleaved
    or corrupted.

    The test creates structured messages and verifies they are received
    intact and in order.
    Without proper locking, concurrent read/write operations could cause
    data corruption
    or message interleaving, which this test will catch.
    """
    client_yamux, server_yamux = yamux_pair
    client_stream: YamuxStream = await client_yamux.open_stream()
    server_stream: YamuxStream = await server_yamux.accept_stream()
    MSG_COUNT = 10
    MSG_SIZE = 256 * 1024  # At max,only DEFAULT_WINDOW_SIZE bytes can be read
    client_msgs = [
        f"CLIENT-MSG-{i:03d}-".encode().ljust(MSG_SIZE, b"C") for i in range(MSG_COUNT)
    ]
    server_msgs = [
        f"SERVER-MSG-{i:03d}-".encode().ljust(MSG_SIZE, b"S") for i in range(MSG_COUNT)
    ]
    client_received = []
    server_received = []

    async def writer(stream, msgs, name):
        """Write messages with minimal delays to encourage race conditions."""
        for i, msg in enumerate(msgs):
            await stream.write(msg)
            # Yield control frequently to encourage interleaving
            if i % 5 == 0:
                await trio.sleep(0.005)

    async def reader(stream, received, name):
        """Read messages and store them for verification."""
        for i in range(MSG_COUNT):
            data = await stream.read(MSG_SIZE)
            received.append(data)
            if i % 3 == 0:
                await trio.sleep(0.001)

    # Running all operations concurrently
    async with trio.open_nursery() as nursery:
        nursery.start_soon(writer, client_stream, client_msgs, "client")
        nursery.start_soon(writer, server_stream, server_msgs, "server")
        nursery.start_soon(reader, client_stream, client_received, "client")
        nursery.start_soon(reader, server_stream, server_received, "server")

    assert len(client_received) == MSG_COUNT, (
        f"Client received {len(client_received)} messages, expected {MSG_COUNT}"
    )
    assert len(server_received) == MSG_COUNT, (
        f"Server received {len(server_received)} messages, expected {MSG_COUNT}"
    )
    assert client_received == server_msgs, (
        "Client did not receive server messages in order or intact!"
    )
    assert server_received == client_msgs, (
        "Server did not receive client messages in order or intact!"
    )
    for i, msg in enumerate(client_received):
        assert len(msg) == MSG_SIZE, (
            f"Client message {i} has wrong size: {len(msg)} != {MSG_SIZE}"
        )

    for i, msg in enumerate(server_received):
        assert len(msg) == MSG_SIZE, (
            f"Server message {i} has wrong size: {len(msg)} != {MSG_SIZE}"
        )

    await client_stream.close()
    await server_stream.close()
