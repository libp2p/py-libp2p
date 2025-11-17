import logging
import platform
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
from libp2p.stream_muxer.exceptions import (
    MuxedConnUnavailable,
)
from libp2p.stream_muxer.yamux.yamux import (
    FLAG_ACK,
    FLAG_FIN,
    FLAG_RST,
    FLAG_SYN,
    GO_AWAY_PROTOCOL_ERROR,
    TYPE_DATA,
    TYPE_PING,
    TYPE_WINDOW_UPDATE,
    YAMUX_HEADER_FORMAT,
    MuxedStreamEOF,
    MuxedStreamError,
    MuxedStreamReset,
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
            return await self.receive_stream.receive_some(8192)
        if n == 0:
            raise ValueError("Reading zero bytes not supported")
        logging.debug(f"Attempting to read {n} bytes")
        with trio.move_on_after(2):
            data = await self.receive_stream.receive_some(n)
            logging.debug(f"Read {len(data)} bytes")
            return data

    async def close(self) -> None:
        logging.debug("Closing stream adapter")
        await self.send_stream.aclose()
        await self.receive_stream.aclose()

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
        nursery.start_soon(client_yamux.start)
        nursery.start_soon(server_yamux.start)
        await trio.sleep(0.1)  # allow start
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


@pytest.mark.trio
async def test_yamux_fin_on_window_update(yamux_pair):
    """
    Tests that a FIN flag is correctly processed when it arrives
    on a WINDOW_UPDATE frame, as per the Yamux spec.
    """
    logging.debug("Starting test_yamux_fin_on_window_update")
    client_yamux, server_yamux = yamux_pair
    client_stream = await client_yamux.open_stream()

    async def read_and_catch_eof(stream):
        with pytest.raises(MuxedStreamEOF, match="Stream is closed for receiving"):
            logging.debug("Test: client_stream.read() blocking...")
            await stream.read()
        logging.debug("Test: client_stream.read() correctly raised EOF")

    async with trio.open_nursery() as nursery:
        nursery.start_soon(read_and_catch_eof, client_stream)
        await trio.sleep(0.1)
        logging.debug("Test: Server injecting WINDOW_UPDATE with FLAG_FIN")
        header = struct.pack(
            YAMUX_HEADER_FORMAT,
            0,
            TYPE_WINDOW_UPDATE,
            FLAG_FIN,
            client_stream.stream_id,
            0,
        )
        await server_yamux.secured_conn.write(header)

    logging.debug("test_yamux_fin_on_window_update complete")


@pytest.mark.trio
async def test_yamux_rst_on_window_update(yamux_pair):
    """
    Tests that a RST flag is correctly processed when it arrives
    on a WINDOW_UPDATE frame, as per the Yamux spec.
    """
    logging.debug("Starting test_yamux_rst_on_window_update")
    client_yamux, server_yamux = yamux_pair
    client_stream = await client_yamux.open_stream()

    async def read_and_catch_reset(stream):
        with pytest.raises(MuxedStreamReset, match="Stream was reset"):
            logging.debug("Test: client_stream.read() blocking...")
            await stream.read()
        logging.debug("Test: client_stream.read() correctly raised Reset")

    async with trio.open_nursery() as nursery:
        nursery.start_soon(read_and_catch_reset, client_stream)
        await trio.sleep(0.1)
        logging.debug("Test: Server injecting WINDOW_UPDATE with FLAG_RST")
        header = struct.pack(
            YAMUX_HEADER_FORMAT,
            0,
            TYPE_WINDOW_UPDATE,
            FLAG_RST,
            client_stream.stream_id,
            0,
        )
        await server_yamux.secured_conn.write(header)

    logging.debug("test_yamux_rst_on_window_update complete")


@pytest.mark.trio
async def test_yamux_accept_stream_unblocks_on_close(yamux_pair):
    """
    Test that accept_stream unblocks when connection closes (fixes #930).

    This test verifies that accept_stream() raises MuxedConnUnavailable when
    the connection is closed, preventing indefinite hangs. This matches the
    behavior of Mplex and QUIC implementations.
    """
    logging.debug("Starting test_yamux_accept_stream_unblocks_on_close")
    client_yamux, server_yamux = yamux_pair

    exception_raised = trio.Event()

    async def close_connection():
        await trio.sleep(0.1)  # Give accept_stream time to start waiting
        logging.debug("Test: Closing server connection")
        await server_yamux.close()

    async def accept_should_unblock():
        with pytest.raises(MuxedConnUnavailable, match="Connection closed"):
            logging.debug("Test: Waiting for accept_stream to unblock")
            await server_yamux.accept_stream()
        # If we reach here, the exception was raised (pytest.raises caught it)
        logging.debug("Test: accept_stream correctly raised MuxedConnUnavailable")
        exception_raised.set()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(accept_should_unblock)
        nursery.start_soon(close_connection)

    # Assert that the exception was raised (test didn't hang)
    assert exception_raised.is_set(), (
        "accept_stream() should have raised MuxedConnUnavailable"
    )
    logging.debug("test_yamux_accept_stream_unblocks_on_close complete")


@pytest.mark.trio
@pytest.mark.skipif(
    platform.system() == "Windows",
    reason=(
        "Directly closing secured_conn during active read causes worker crash "
        "on Windows due to platform I/O semantics. The main functionality is "
        "tested by test_yamux_accept_stream_unblocks_on_close which works on "
        "all platforms. See 1014-WINDOWS-TEST-FAILURE-ANALYSIS.md for details."
    ),
)
async def test_yamux_accept_stream_unblocks_on_error(yamux_pair):
    """
    Test that accept_stream unblocks when connection closes due to error.

    This verifies the fix works for error scenarios, not just clean closes.
    We close the underlying raw connection to simulate a network error.

    Note: Skipped on Windows because directly closing connections during active
    read causes a fatal worker crash. The core functionality is fully tested by
    test_yamux_accept_stream_unblocks_on_close which works on all platforms.
    """
    logging.debug("Starting test_yamux_accept_stream_unblocks_on_error")
    client_yamux, server_yamux = yamux_pair

    exception_raised = trio.Event()

    async def trigger_error():
        await trio.sleep(0.1)  # Give accept_stream time to start waiting
        logging.debug("Test: Closing underlying raw connection to trigger error")
        # Close the underlying raw connection to simulate a network error
        # This is more reliable than closing secured_conn directly
        raw_conn = server_yamux.secured_conn.conn
        await raw_conn.close()

    async def accept_should_unblock():
        with pytest.raises(MuxedConnUnavailable, match="Connection closed"):
            logging.debug("Test: Waiting for accept_stream to unblock")
            await server_yamux.accept_stream()
        # If we reach here, the exception was raised (pytest.raises caught it)
        logging.debug("Test: accept_stream correctly raised MuxedConnUnavailable")
        exception_raised.set()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(accept_should_unblock)
        nursery.start_soon(trigger_error)

    # Assert that the exception was raised (test didn't hang)
    assert exception_raised.is_set(), (
        "accept_stream() should have raised MuxedConnUnavailable"
    )
    logging.debug("test_yamux_accept_stream_unblocks_on_error complete")


@pytest.mark.trio
async def test_yamux_syn_with_data(yamux_pair):
    """Test that data sent with SYN frame is properly received and buffered."""
    logging.debug("Starting test_yamux_syn_with_data")
    client_yamux, server_yamux = yamux_pair

    # Manually construct a SYN frame with accompanying data
    test_data = b"data with SYN frame"
    stream_id = 1  # Client stream ID (odd number)

    # Create SYN header with data length
    syn_header = struct.pack(
        YAMUX_HEADER_FORMAT,
        0,  # version
        TYPE_DATA,  # type
        FLAG_SYN,  # flags
        stream_id,
        len(test_data),  # length of accompanying data
    )

    # Send SYN with data directly
    await client_yamux.secured_conn.write(syn_header + test_data)
    logging.debug(f"Sent SYN with {len(test_data)} bytes of data")

    # Server should accept the stream and have data already buffered
    server_stream = await server_yamux.accept_stream()
    assert server_stream.stream_id == stream_id

    # Verify the data was buffered and is immediately available
    received = await server_stream.read(len(test_data))
    assert received == test_data, "Data sent with SYN should be immediately available"
    logging.debug("test_yamux_syn_with_data complete")


@pytest.mark.trio
async def test_yamux_ack_with_data(yamux_pair):
    """Test that data sent with ACK frame is properly received and buffered."""
    logging.debug("Starting test_yamux_ack_with_data")
    client_yamux, server_yamux = yamux_pair

    # Client opens a stream (sends SYN)
    client_stream = await client_yamux.open_stream()
    stream_id = client_stream.stream_id

    # Wait for server to receive SYN and respond with ACK
    await trio.sleep(0.1)

    # Now manually send data with an ACK flag from server to client
    test_data = b"data with ACK frame"
    ack_header = struct.pack(
        YAMUX_HEADER_FORMAT,
        0,  # version
        TYPE_DATA,  # type
        FLAG_ACK,  # flags (ACK flag set)
        stream_id,
        len(test_data),  # length of accompanying data
    )

    # Send ACK with data from server to client
    await server_yamux.secured_conn.write(ack_header + test_data)
    logging.debug(f"Sent ACK with {len(test_data)} bytes of data")

    # Wait for the data to be processed
    await trio.sleep(0.1)

    # Verify the data was buffered on the client side
    # Since the stream is already open, the data should be in the buffer
    async with client_yamux.streams_lock:
        assert stream_id in client_yamux.stream_buffers
        assert len(client_yamux.stream_buffers[stream_id]) >= len(test_data)
        buffered_data = bytes(client_yamux.stream_buffers[stream_id][: len(test_data)])
        # Remove the data we just checked
        client_yamux.stream_buffers[stream_id] = client_yamux.stream_buffers[stream_id][
            len(test_data) :
        ]

    assert buffered_data == test_data, "Data sent with ACK should be buffered"
    logging.debug("test_yamux_ack_with_data complete")


@pytest.mark.trio
async def test_yamux_syn_with_empty_data(yamux_pair):
    """Test that SYN frame with zero-length data is handled correctly."""
    logging.debug("Starting test_yamux_syn_with_empty_data")
    client_yamux, server_yamux = yamux_pair

    # Manually construct a SYN frame with no data (length = 0)
    stream_id = 3  # Client stream ID (odd number)

    syn_header = struct.pack(
        YAMUX_HEADER_FORMAT,
        0,  # version
        TYPE_DATA,  # type
        FLAG_SYN,  # flags
        stream_id,
        0,  # length = 0, no accompanying data
    )

    # Send SYN with no data
    await client_yamux.secured_conn.write(syn_header)
    logging.debug("Sent SYN with no data")

    # Server should accept the stream
    server_stream = await server_yamux.accept_stream()
    assert server_stream.stream_id == stream_id

    # Verify no data is in the buffer
    async with server_yamux.streams_lock:
        assert len(server_yamux.stream_buffers[stream_id]) == 0

    logging.debug("test_yamux_syn_with_empty_data complete")


@pytest.mark.trio
async def test_yamux_syn_with_large_data(yamux_pair):
    """Test that large data sent with SYN frame is properly handled."""
    logging.debug("Starting test_yamux_syn_with_large_data")
    client_yamux, server_yamux = yamux_pair

    # Create large test data (but within window size)
    test_data = b"X" * 1024  # 1KB of data
    stream_id = 5  # Client stream ID (odd number)

    syn_header = struct.pack(
        YAMUX_HEADER_FORMAT,
        0,  # version
        TYPE_DATA,  # type
        FLAG_SYN,  # flags
        stream_id,
        len(test_data),
    )

    # Send SYN with large data
    await client_yamux.secured_conn.write(syn_header + test_data)
    logging.debug(f"Sent SYN with {len(test_data)} bytes of large data")

    # Server should accept the stream and have all data buffered
    server_stream = await server_yamux.accept_stream()
    assert server_stream.stream_id == stream_id

    # Verify all data was buffered correctly
    received = await server_stream.read(len(test_data))
    assert received == test_data
    assert len(received) == 1024
    logging.debug("test_yamux_syn_with_large_data complete")
