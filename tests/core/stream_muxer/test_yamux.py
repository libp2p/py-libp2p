import logging
import struct

import pytest
import trio
from trio.testing import (
    memory_stream_pair,
)

from libp2p.abc import (
    IRawConnection,
)
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
    FLAG_SYN,
    GO_AWAY_PROTOCOL_ERROR,
    TYPE_PING,
    TYPE_WINDOW_UPDATE,
    YAMUX_HEADER_FORMAT,
    MuxedStreamEOF,
    MuxedStreamError,
    Yamux,
    YamuxStream,
)


class TrioStreamAdapter(IRawConnection):
    def __init__(self, send_stream, receive_stream, is_initiator: bool = False):
        self.send_stream = send_stream
        self.receive_stream = receive_stream
        self.is_initiator = is_initiator

    async def write(self, data: bytes) -> None:
        logging.debug(f"Writing {len(data)} bytes")
        with trio.move_on_after(2):
            await self.send_stream.send_all(data)

    async def read(self, n: int | None = None) -> bytes:
        if n is None or n == -1:
            raise ValueError("Reading unbounded not supported")
        logging.debug(f"Attempting to read {n} bytes")
        with trio.move_on_after(2):
            data = await self.receive_stream.receive_some(n)
            logging.debug(f"Read {len(data)} bytes")
            return data

    async def close(self) -> None:
        logging.debug("Closing stream")

    def get_remote_address(self) -> tuple[str, int] | None:
        # Return None since this is a test adapter without real network info
        return None


@pytest.fixture
def key_pair():
    return create_new_key_pair()


@pytest.fixture
def peer_id(key_pair):
    return ID.from_pubkey(key_pair.public_key)


@pytest.fixture
async def secure_conn_pair(key_pair, peer_id):
    logging.debug("Setting up secure_conn_pair")
    client_send, server_receive = memory_stream_pair()
    server_send, client_receive = memory_stream_pair()

    client_rw = TrioStreamAdapter(client_send, client_receive, is_initiator=True)
    server_rw = TrioStreamAdapter(server_send, server_receive, is_initiator=False)

    insecure_transport = InsecureTransport(key_pair, peerstore=None)

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
async def test_yamux_stream_creation(yamux_pair):
    logging.debug("Starting test_yamux_stream_creation")
    client_yamux, server_yamux = yamux_pair
    assert client_yamux.is_initiator
    assert not server_yamux.is_initiator
    with trio.move_on_after(5):
        stream = await client_yamux.open_stream()
        logging.debug("Stream opened")
        assert isinstance(stream, YamuxStream)
        assert stream.stream_id % 2 == 1
    logging.debug("test_yamux_stream_creation complete")


@pytest.mark.trio
async def test_yamux_accept_stream(yamux_pair):
    logging.debug("Starting test_yamux_accept_stream")
    client_yamux, server_yamux = yamux_pair
    client_stream = await client_yamux.open_stream()
    server_stream = await server_yamux.accept_stream()
    assert server_stream.stream_id == client_stream.stream_id
    assert isinstance(server_stream, YamuxStream)
    logging.debug("test_yamux_accept_stream complete")


@pytest.mark.trio
async def test_yamux_data_transfer(yamux_pair):
    logging.debug("Starting test_yamux_data_transfer")
    client_yamux, server_yamux = yamux_pair
    client_stream = await client_yamux.open_stream()
    server_stream = await server_yamux.accept_stream()
    test_data = b"hello yamux"
    await client_stream.write(test_data)
    received = await server_stream.read(len(test_data))
    assert received == test_data
    reply_data = b"hi back"
    await server_stream.write(reply_data)
    received = await client_stream.read(len(reply_data))
    assert received == reply_data
    logging.debug("test_yamux_data_transfer complete")


@pytest.mark.trio
async def test_yamux_stream_close(yamux_pair):
    logging.debug("Starting test_yamux_stream_close")
    client_yamux, server_yamux = yamux_pair
    client_stream = await client_yamux.open_stream()
    server_stream = await server_yamux.accept_stream()

    # Send some data first so we have something in the buffer
    test_data = b"test data before close"
    await client_stream.write(test_data)

    # Close the client stream
    await client_stream.close()

    # Wait a moment for the FIN to be processed
    await trio.sleep(0.1)

    # Verify client stream marking
    assert client_stream.send_closed, "Client stream should be marked as send_closed"

    # Read from server - should return the data that was sent
    received = await server_stream.read(len(test_data))
    assert received == test_data

    # Now try to read again, expecting EOF exception
    try:
        await server_stream.read(1)
    except MuxedStreamEOF:
        pass

    # Close server stream too to fully close the connection
    await server_stream.close()

    # Wait for both sides to process
    await trio.sleep(0.1)

    # Now both directions are closed, so stream should be fully closed
    assert client_stream.closed, (
        "Client stream should be fully closed after bidirectional close"
    )

    # Writing should still fail
    with pytest.raises(MuxedStreamError):
        await client_stream.write(b"test")

    logging.debug("test_yamux_stream_close complete")


@pytest.mark.trio
async def test_yamux_stream_reset(yamux_pair):
    logging.debug("Starting test_yamux_stream_reset")
    client_yamux, server_yamux = yamux_pair
    client_stream = await client_yamux.open_stream()
    server_stream = await server_yamux.accept_stream()
    await client_stream.reset()
    # After reset, reading should raise MuxedStreamReset or MuxedStreamEOF
    try:
        await server_stream.read()
    except (MuxedStreamEOF, MuxedStreamError):
        pass
    else:
        pytest.fail("Expected MuxedStreamEOF or MuxedStreamError")
    # Verify subsequent operations fail with StreamReset or EOF
    with pytest.raises(MuxedStreamError):
        await server_stream.read()
    with pytest.raises(MuxedStreamError):
        await server_stream.write(b"test")
    logging.debug("test_yamux_stream_reset complete")


@pytest.mark.trio
async def test_yamux_connection_close(yamux_pair):
    logging.debug("Starting test_yamux_connection_close")
    client_yamux, server_yamux = yamux_pair
    await client_yamux.open_stream()
    await server_yamux.accept_stream()
    await client_yamux.close()
    logging.debug("Closing stream")
    await trio.sleep(0.2)
    assert client_yamux.is_closed
    assert server_yamux.event_shutting_down.is_set()
    logging.debug("test_yamux_connection_close complete")


@pytest.mark.trio
async def test_yamux_deadlines_raise_not_implemented(yamux_pair):
    logging.debug("Starting test_yamux_deadlines_raise_not_implemented")
    client_yamux, _ = yamux_pair
    stream = await client_yamux.open_stream()
    with trio.move_on_after(2):
        with pytest.raises(
            NotImplementedError, match="Yamux does not support setting read deadlines"
        ):
            stream.set_deadline(60)
    logging.debug("test_yamux_deadlines_raise_not_implemented complete")


@pytest.mark.trio
async def test_yamux_flow_control(yamux_pair):
    logging.debug("Starting test_yamux_flow_control")
    client_yamux, server_yamux = yamux_pair
    client_stream = await client_yamux.open_stream()
    server_stream = await server_yamux.accept_stream()

    # Track initial window size
    initial_window = client_stream.send_window

    # Create a large chunk of data that will use a significant portion of the window
    large_data = b"x" * (initial_window // 2)

    # Send the data
    await client_stream.write(large_data)

    # Check that window was reduced
    assert client_stream.send_window < initial_window, (
        "Window should be reduced after sending"
    )

    # Read the data on the server side
    received = b""
    while len(received) < len(large_data):
        chunk = await server_stream.read(1024)
        if not chunk:
            break
        received += chunk

    assert received == large_data, "Server should receive all data sent"

    # Calculate a significant window update - at least doubling current window
    window_update_size = initial_window

    # Explicitly send a larger window update from server to client
    window_update_header = struct.pack(
        YAMUX_HEADER_FORMAT,
        0,
        TYPE_WINDOW_UPDATE,
        0,
        client_stream.stream_id,
        window_update_size,
    )
    await server_yamux.secured_conn.write(window_update_header)

    # Wait for client to process the window update
    await trio.sleep(0.2)

    # Check that client's send window was increased
    # Since we're explicitly sending a large update, it should now be larger
    logging.debug(
        f"Window after update:"
        f" {client_stream.send_window},"
        f"initial half: {initial_window // 2}"
    )
    assert client_stream.send_window > initial_window // 2, (
        "Window should be increased after update"
    )

    await client_stream.close()
    await server_stream.close()
    logging.debug("test_yamux_flow_control complete")


@pytest.mark.trio
async def test_yamux_half_close(yamux_pair):
    logging.debug("Starting test_yamux_half_close")
    client_yamux, server_yamux = yamux_pair
    client_stream = await client_yamux.open_stream()
    server_stream = await server_yamux.accept_stream()

    # Send some initial data
    init_data = b"initial data"
    await client_stream.write(init_data)

    # Client closes sending side
    await client_stream.close()
    await trio.sleep(0.1)

    # Verify state
    assert client_stream.send_closed, "Client stream should be marked as send_closed"
    assert not client_stream.closed, "Client stream should not be fully closed yet"

    # Check that server receives the initial data
    received = await server_stream.read(len(init_data))
    assert received == init_data, "Server should receive data sent before FIN"

    # When trying to read more, it should get EOF
    try:
        await server_stream.read(1)
    except MuxedStreamEOF:
        pass

    # Server can still write to client
    test_data = b"server response after client close"

    # The server shouldn't be marked as send_closed yet
    assert not server_stream.send_closed, (
        "Server stream shouldn't be marked as send_closed"
    )

    await server_stream.write(test_data)

    # Client can still read
    received = await client_stream.read(len(test_data))
    assert received == test_data, (
        "Client should still be able to read after sending FIN"
    )

    # Now server closes its sending side
    await server_stream.close()
    await trio.sleep(0.1)

    # Both streams should now be fully closed
    assert client_stream.closed, "Client stream should be fully closed"
    assert server_stream.closed, "Server stream should be fully closed"

    logging.debug("test_yamux_half_close complete")


@pytest.mark.trio
async def test_yamux_ping(yamux_pair):
    logging.debug("Starting test_yamux_ping")
    client_yamux, server_yamux = yamux_pair

    # Send a ping from client to server
    ping_value = 12345

    # Send ping directly
    ping_header = struct.pack(
        YAMUX_HEADER_FORMAT, 0, TYPE_PING, FLAG_SYN, 0, ping_value
    )
    await client_yamux.secured_conn.write(ping_header)
    logging.debug(f"Sent ping with value {ping_value}")

    # Wait for ping to be processed
    await trio.sleep(0.2)

    # Simple success is no exception
    logging.debug("test_yamux_ping complete")


@pytest.mark.trio
async def test_yamux_go_away_with_error(yamux_pair):
    logging.debug("Starting test_yamux_go_away_with_error")
    client_yamux, server_yamux = yamux_pair

    # Send GO_AWAY with protocol error
    await client_yamux.close(GO_AWAY_PROTOCOL_ERROR)

    # Wait for server to process
    await trio.sleep(0.2)

    # Verify server recognized shutdown
    assert server_yamux.event_shutting_down.is_set(), (
        "Server should be shutting down after GO_AWAY"
    )

    logging.debug("test_yamux_go_away_with_error complete")


@pytest.mark.trio
async def test_yamux_backpressure(yamux_pair):
    logging.debug("Starting test_yamux_backpressure")
    client_yamux, server_yamux = yamux_pair

    # Test backpressure by opening many streams
    streams = []
    stream_count = 10  # Open several streams to test backpressure

    # Open streams from client
    for _ in range(stream_count):
        stream = await client_yamux.open_stream()
        streams.append(stream)

    # All streams should be created successfully
    assert len(streams) == stream_count, "All streams should be created"

    # Accept all streams on server side
    server_streams = []
    for _ in range(stream_count):
        server_stream = await server_yamux.accept_stream()
        server_streams.append(server_stream)

    # Verify server side has all the streams
    assert len(server_streams) == stream_count, "Server should accept all streams"

    # Close all streams
    for stream in streams:
        await stream.close()
    for stream in server_streams:
        await stream.close()

    logging.debug("test_yamux_backpressure complete")
