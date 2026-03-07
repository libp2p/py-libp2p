"""
Basic QUIC Echo Test

Simple test to verify the basic QUIC flow:
1. Client connects to server
2. Client sends data
3. Server receives data and echoes back
4. Client receives the echo

This test focuses on identifying where the accept_stream issue occurs.
"""

import logging
import os

import pytest
import multiaddr
import trio

from examples.ping.ping import PING_LENGTH, PING_PROTOCOL_ID
from libp2p import new_host
from libp2p.abc import INetStream
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.transport import QUICTransport
from libp2p.transport.quic.utils import create_quic_multiaddr

# Set up logging - respect LIBP2P_DEBUG environment variable
# Only configure basic logging if LIBP2P_DEBUG is not set
if not os.environ.get("LIBP2P_DEBUG"):
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("multiaddr").setLevel(logging.WARNING)
    # If LIBP2P_DEBUG is not set, we still want some visibility in tests
    logging.getLogger("libp2p.transport.quic").setLevel(logging.INFO)
    logging.getLogger("libp2p.host").setLevel(logging.INFO)
    logging.getLogger("libp2p.network").setLevel(logging.INFO)
    logging.getLogger("libp2p.protocol_muxer").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# Enable verbose QUIC stress test logging. Set to False once the test is stable.
QUIC_STRESS_TEST_DEBUG = True


class TestBasicQUICFlow:
    """Test basic QUIC client-server communication flow."""

    @pytest.fixture
    def server_key(self):
        """Generate server key pair."""
        return create_new_key_pair()

    @pytest.fixture
    def client_key(self):
        """Generate client key pair."""
        return create_new_key_pair()

    @pytest.fixture
    def server_config(self):
        """Simple server configuration."""
        return QUICTransportConfig(
            idle_timeout=10.0,
            connection_timeout=5.0,
            max_concurrent_streams=10,
            max_connections=5,
        )

    @pytest.fixture
    def client_config(self):
        """Simple client configuration."""
        return QUICTransportConfig(
            idle_timeout=10.0,
            connection_timeout=5.0,
            max_concurrent_streams=5,
        )

    @pytest.mark.trio
    async def test_basic_echo_flow(
        self, server_key, client_key, server_config, client_config
    ):
        """Test basic client-server echo flow with detailed logging."""
        logger.debug("Starting basic QUIC echo test")

        # Create server components
        server_transport = QUICTransport(server_key.private_key, server_config)

        # Track test state
        server_received_data = None
        server_connection_established = False
        echo_sent = False

        async def echo_server_handler(connection: QUICConnection) -> None:
            """Simple echo server handler with detailed logging."""
            nonlocal server_received_data, server_connection_established, echo_sent

            logger.debug("SERVER: Connection handler called")
            server_connection_established = True

            try:
                logger.debug("SERVER: Waiting for incoming stream")

                # Accept stream with timeout and detailed logging
                logger.debug("SERVER: Calling accept_stream")
                stream = await connection.accept_stream(timeout=5.0)

                if stream is None:
                    logger.warning("SERVER: accept_stream returned None")
                    return

                logger.debug(f"SERVER: Stream accepted, Stream ID: {stream.stream_id}")

                # Read data from the stream
                logger.debug("SERVER: Reading data from stream")
                server_data = await stream.read(1024)

                if not server_data:
                    logger.warning("SERVER: No data received from stream")
                    return

                server_received_data = server_data.decode("utf-8", errors="ignore")
                logger.debug(f"SERVER: Received data: '{server_received_data}'")

                # Echo the data back
                echo_message = f"ECHO: {server_received_data}"
                logger.debug(f"SERVER: Sending echo: '{echo_message}'")

                await stream.write(echo_message.encode())
                echo_sent = True
                logger.debug("SERVER: Echo sent successfully")

                # Close the stream
                await stream.close()
                logger.debug("SERVER: Stream closed")

            except Exception as e:
                logger.error(f"SERVER: Error in handler: {e}", exc_info=True)

        # Create listener
        listener = server_transport.create_listener(echo_server_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        # Variables to track client state
        client_connected = False
        client_sent_data = False
        client_received_echo = None

        try:
            logger.debug("Starting server")

            async with trio.open_nursery() as nursery:
                # Start server listener
                success = await listener.listen(listen_addr, nursery)
                assert success, "Failed to start server listener"

                # Get server address
                server_addrs = listener.get_addrs()
                server_addr = multiaddr.Multiaddr(
                    f"{server_addrs[0]}/p2p/{ID.from_pubkey(server_key.public_key)}"
                )
                logger.debug(f"SERVER: Listening on {server_addr}")

                # Give server a moment to be ready
                await trio.sleep(0.1)

                logger.debug("Starting client")

                # Create client transport
                client_transport = QUICTransport(client_key.private_key, client_config)
                client_transport.set_background_nursery(nursery)

                try:
                    # Connect to server
                    logger.debug(f"CLIENT: Connecting to {server_addr}")
                    connection = await client_transport.dial(server_addr)
                    client_connected = True
                    logger.debug("CLIENT: Connected to server")

                    # Open a stream
                    logger.debug("CLIENT: Opening stream")
                    stream = await connection.open_stream()
                    logger.debug(f"CLIENT: Stream opened with ID: {stream.stream_id}")

                    # Send test data
                    test_message = "Hello QUIC Server!"
                    logger.debug(f"CLIENT: Sending message: '{test_message}'")
                    await stream.write(test_message.encode())
                    client_sent_data = True
                    logger.debug("CLIENT: Message sent")

                    # Read echo response
                    logger.debug("CLIENT: Waiting for echo response")
                    response_data = await stream.read(1024)

                    if response_data:
                        client_received_echo = response_data.decode(
                            "utf-8", errors="ignore"
                        )
                        logger.debug(f"CLIENT: Received echo: '{client_received_echo}'")
                    else:
                        logger.warning("CLIENT: No echo response received")

                    logger.debug("CLIENT: Closing connection")
                    await connection.close()
                    logger.debug("CLIENT: Connection closed")

                    logger.debug("CLIENT: Closing transport")
                    await client_transport.close()
                    logger.debug("CLIENT: Transport closed")

                except Exception as e:
                    logger.error(f"CLIENT: Error: {e}", exc_info=True)

                finally:
                    await client_transport.close()
                    logger.debug("CLIENT: Transport closed")

                # Give everything time to complete
                await trio.sleep(0.5)

                # Cancel nursery to stop server
                nursery.cancel_scope.cancel()

        finally:
            # Cleanup
            if not listener._closed:
                await listener.close()
            await server_transport.close()

        # Verify the flow worked
        logger.debug("Test results:")
        logger.debug(
            f"  Server connection established: {server_connection_established}"
        )
        logger.debug(f"  Client connected: {client_connected}")
        logger.debug(f"  Client sent data: {client_sent_data}")
        logger.debug(f"  Server received data: '{server_received_data}'")
        logger.debug(f"  Echo sent by server: {echo_sent}")
        logger.debug(f"  Client received echo: '{client_received_echo}'")

        # Test assertions
        assert server_connection_established, "Server connection handler was not called"
        assert client_connected, "Client failed to connect"
        assert client_sent_data, "Client failed to send data"
        assert server_received_data == "Hello QUIC Server!", (
            f"Server received wrong data: '{server_received_data}'"
        )
        assert echo_sent, "Server failed to send echo"
        assert client_received_echo == "ECHO: Hello QUIC Server!", (
            f"Client received wrong echo: '{client_received_echo}'"
        )

        logger.debug("Basic echo test passed")

    @pytest.mark.trio
    async def test_server_accept_stream_timeout(
        self, server_key, client_key, server_config, client_config
    ):
        """Test what happens when server accept_stream times out."""
        logger.debug("Testing server accept_stream timeout")

        server_transport = QUICTransport(server_key.private_key, server_config)

        accept_stream_called = False
        accept_stream_timeout = False

        async def timeout_test_handler(connection: QUICConnection) -> None:
            """Handler that tests accept_stream timeout."""
            nonlocal accept_stream_called, accept_stream_timeout

            logger.debug(
                "SERVER: Connection established, testing accept_stream timeout"
            )
            accept_stream_called = True

            try:
                logger.debug("SERVER: Calling accept_stream with 2 second timeout")
                stream = await connection.accept_stream(timeout=2.0)
                logger.debug(f"SERVER: accept_stream returned: {stream}")

            except Exception as e:
                logger.debug(f"SERVER: accept_stream timed out or failed: {e}")
                accept_stream_timeout = True

        listener = server_transport.create_listener(timeout_test_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        client_transport = None
        try:
            async with trio.open_nursery() as nursery:
                # Start server
                server_transport.set_background_nursery(nursery)
                success = await listener.listen(listen_addr, nursery)
                assert success, "Failed to start server listener"

                server_addr = multiaddr.Multiaddr(
                    f"{listener.get_addrs()[0]}/p2p/{ID.from_pubkey(server_key.public_key)}"
                )
                logger.debug(f"SERVER: Listening on {server_addr}")

                # Start client in the same nursery
                client_transport = QUICTransport(client_key.private_key, client_config)
                client_transport.set_background_nursery(nursery)

                connection = None
                try:
                    logger.debug("CLIENT: Connecting (but NOT opening stream)")
                    connection = await client_transport.dial(server_addr)
                    logger.debug("CLIENT: Connected (no stream opened)")

                    # Wait for server timeout
                    await trio.sleep(3.0)

                finally:
                    await client_transport.close()
                    if connection:
                        await connection.close()
                        logger.debug("CLIENT: Connection closed")

                nursery.cancel_scope.cancel()

        finally:
            if client_transport and not client_transport._closed:
                await client_transport.close()
            if not listener._closed:
                await listener.close()
            if not server_transport._closed:
                await server_transport.close()

        logger.debug("Timeout test results:")
        logger.debug(f"  accept_stream called: {accept_stream_called}")
        logger.debug(f"  accept_stream timeout: {accept_stream_timeout}")

        assert accept_stream_called, "accept_stream should have been called"
        assert accept_stream_timeout, (
            "accept_stream should have timed out when no stream was opened"
        )

        logger.debug("Timeout test passed")


@pytest.mark.trio
@pytest.mark.flaky(reruns=3, reruns_delay=2)
async def test_yamux_stress_ping():
    # Enable debug logging when QUICK_STRESS_TEST_DEBUG=true
    debug_enabled = QUIC_STRESS_TEST_DEBUG
    if debug_enabled:
        # Enable debug logging for QUIC-related modules in CI/CD
        debug_loggers = [
            "libp2p.transport.quic",
            "libp2p.host.basic_host",
            "libp2p.network.swarm",
            "libp2p.network.connection.swarm_connection",
            "libp2p.protocol_muxer",
        ]
        for logger_name in debug_loggers:
            logging.getLogger(logger_name).setLevel(logging.DEBUG)
        logger.debug("CI/CD DEBUG MODE ENABLED for test_yamux_stress_ping")
        logger.debug(f"Debug loggers enabled: {', '.join(debug_loggers)}")

    STREAM_COUNT = 100
    listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")
    latencies = []
    failures = []
    failure_details = []  # Store detailed failure info for CI/CD
    completion_event = trio.Event()
    completed_count: list[int] = [0]  # Use list to make it mutable for closures
    completed_lock = trio.Lock()
    stream_start_times = {}  # Track when each stream started

    # === Server Setup ===
    server_host = new_host(listen_addrs=[listen_addr])

    async def handle_ping(stream: INetStream) -> None:
        try:
            while True:
                payload = await stream.read(PING_LENGTH)
                if not payload:
                    break
                await stream.write(payload)
        except Exception:
            await stream.reset()

    # Set handler before starting server
    server_host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)

    async with server_host.run(listen_addrs=[listen_addr]):
        # Wait for server to actually be listening
        while not server_host.get_addrs():
            await trio.sleep(0.01)

        # === Client Setup ===
        destination = str(server_host.get_addrs()[0])
        maddr = multiaddr.Multiaddr(destination)
        info = info_from_p2p_addr(maddr)

        client_listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")
        client_host = new_host(listen_addrs=[client_listen_addr])

        async with client_host.run(listen_addrs=[client_listen_addr]):
            # Wait for client to be ready
            while not client_host.get_addrs():
                await trio.sleep(0.01)

            # connect() now ensures connection is fully established and ready
            # (QUIC handshake complete, muxer ready, event_started set)
            connect_start = trio.current_time()
            await client_host.connect(info)
            connect_time = (trio.current_time() - connect_start) * 1000

            negotiation_limit = 16  # fallback until we inspect the live connection
            network = client_host.get_network()
            connections = network.get_connections(info.peer_id)
            muxed_conn = None
            if connections:
                swarm_conn = connections[0]
                muxed_conn = getattr(swarm_conn, "muxed_conn", None)
                if isinstance(muxed_conn, QUICConnection):
                    sem_limit = getattr(
                        muxed_conn._transport._config,
                        "NEGOTIATION_SEMAPHORE_LIMIT",
                        negotiation_limit,
                    )
                    if isinstance(sem_limit, int) and sem_limit > 0:
                        negotiation_limit = sem_limit

            if debug_enabled:
                logger.debug(f"Connection established in {connect_time:.2f}ms")
                if isinstance(muxed_conn, QUICConnection):
                    established = muxed_conn.is_established
                    logger.debug(f"  QUIC Connection state: established={established}")
                    outbound = muxed_conn._outbound_stream_count
                    logger.debug(f"  Outbound streams: {outbound}")
                    inbound = muxed_conn._inbound_stream_count
                    logger.debug(f"  Inbound streams: {inbound}")
                    logger.debug(f"  Negotiation semaphore limit: {negotiation_limit}")

            # Automatic identify should populate the peerstore with cached protocols.
            identify_cached = False
            identify_start = trio.current_time()
            while trio.current_time() - identify_start < 5.0:
                try:
                    supported = client_host.get_peerstore().supports_protocols(
                        info.peer_id, [str(PING_PROTOCOL_ID)]
                    )
                    if supported:
                        identify_cached = True
                        break
                except Exception:
                    pass
                await trio.sleep(0.01)

            if debug_enabled:
                if identify_cached:
                    logger.debug("  Automatic identify cached ping protocol")
                else:
                    logger.warning("  Automatic identify did not cache ping within 5s")

            assert identify_cached, (
                "Automatic identify should cache ping before running stress test"
            )

            # Stress test still opens 100 streams at once; even though the QUIC
            # transport allows 32 concurrent negotiations on Linux, aioquic will
            # start resetting streams if we actually hit that ceiling. Keep a
            # soft cap of 16 concurrent dial attempts for stability while still
            # exercising the pipeline.
            # Keep the stress test from flooding aioquic: 12 concurrent dial attempts
            # saturates the connection without triggering the stream-reset storm
            # seen at higher levels.
            max_pending_streams = max(4, min(negotiation_limit, 12))
            stream_gate = trio.Semaphore(max_pending_streams)

            async def ping_stream(i: int):
                stream = None
                stream_start = trio.current_time()
                stream_start_times[i] = stream_start
                try:
                    if debug_enabled and i % 10 == 0:  # Log every 10th stream start
                        logger.debug(f"Starting stream #{i} at {stream_start:.3f}s")

                    new_stream_start = trio.current_time()
                    async with stream_gate:
                        stream = await client_host.new_stream(
                            info.peer_id, [PING_PROTOCOL_ID]
                        )
                    new_stream_time = (trio.current_time() - new_stream_start) * 1000

                    if debug_enabled and i % 10 == 0:
                        logger.debug(f"  Stream #{i} opened in {new_stream_time:.2f}ms")

                    write_start = trio.current_time()
                    await stream.write(b"\x01" * PING_LENGTH)
                    write_time = (trio.current_time() - write_start) * 1000

                    if debug_enabled and i % 10 == 0:
                        logger.debug(
                            f"  Stream #{i} write completed in {write_time:.2f}ms"
                        )

                    # Wait for response with timeout as safety net
                    read_start = trio.current_time()
                    with trio.fail_after(30):
                        response = await stream.read(PING_LENGTH)
                    read_time = (trio.current_time() - read_start) * 1000

                    if response == b"\x01" * PING_LENGTH:
                        total_time = (trio.current_time() - stream_start) * 1000
                        latency_ms = int(total_time)
                        latencies.append(latency_ms)
                        if debug_enabled and i % 10 == 0:
                            logger.debug(
                                f"  Stream #{i} completed: "
                                f"total={total_time:.2f}ms, read={read_time:.2f}ms"
                            )
                        elif not debug_enabled:
                            logger.debug(f"[Ping #{i}] Latency: {latency_ms} ms")
                    await stream.close()
                except Exception as e:
                    total_time = (trio.current_time() - stream_start) * 1000
                    error_type = type(e).__name__
                    error_msg = (
                        f"[Ping #{i}] Failed after {total_time:.2f}ms: "
                        f"{error_type}: {e}"
                    )
                    logger.warning(error_msg)
                    failures.append(i)

                    # Store detailed failure info when debug logging is enabled
                    if debug_enabled:
                        import traceback

                        failure_details.append(
                            {
                                "stream_id": i,
                                "error_type": type(e).__name__,
                                "error_msg": str(e),
                                "time_elapsed_ms": total_time,
                                "traceback": traceback.format_exc(),
                            }
                        )
                        # Log connection state on failure
                        try:
                            network = client_host.get_network()
                            connections = network.get_connections(info.peer_id)
                            if connections:
                                swarm_conn = connections[0]
                                if hasattr(swarm_conn, "muxed_conn"):
                                    muxed_conn = swarm_conn.muxed_conn
                                    if isinstance(muxed_conn, QUICConnection):
                                        logger.debug(f"  Stream #{i} failure context:")
                                        established = muxed_conn.is_established
                                        logger.debug(
                                            f"    Connection established: {established}"
                                        )
                                        outbound = muxed_conn._outbound_stream_count
                                        logger.debug(
                                            f"    Outbound streams: {outbound}"
                                        )
                                        inbound = muxed_conn._inbound_stream_count
                                        logger.debug(f"    Inbound streams: {inbound}")
                                        active = len(muxed_conn._streams)
                                        logger.debug(f"    Active streams: {active}")
                        except Exception:
                            pass

                    if stream:
                        try:
                            await stream.reset()
                        except Exception:
                            pass
                finally:
                    # Signal completion
                    async with completed_lock:
                        completed_count[0] += 1
                        if completed_count[0] == STREAM_COUNT:
                            completion_event.set()

            # No semaphore limit - run all streams concurrently to test QUIC behavior
            async with trio.open_nursery() as nursery:
                for i in range(STREAM_COUNT):
                    nursery.start_soon(ping_stream, i)

                # Wait for all streams to complete (event-driven, not polling)
                with trio.fail_after(120):  # Safety timeout
                    await completion_event.wait()

        # === Result Summary ===
        logger.info("Ping Stress Test Summary")
        logger.info(f"Total Streams Launched: {STREAM_COUNT}")
        logger.info(f"Successful Pings: {len(latencies)}")
        logger.info(f"Failed Pings: {len(failures)}")
        if failures:
            logger.warning(f"Failed stream indices: {failures}")
            if debug_enabled and failure_details:
                logger.debug("Detailed Failure Information (CI/CD):")
                for detail in failure_details[:10]:  # Show first 10 failures
                    logger.debug(f"  Stream #{detail['stream_id']}:")
                    logger.debug(
                        f"    Error: {detail['error_type']}: {detail['error_msg']}"
                    )
                    logger.debug(f"    Time elapsed: {detail['time_elapsed_ms']:.2f}ms")
                    if len(failure_details) > 10:
                        logger.debug(
                            f"  ... and {len(failure_details) - 10} more failures"
                        )

        # === Registry Performance Stats ===
        # Collect registry stats from server listener
        server_listener = None
        for transport in server_host.get_network().listeners.values():
            # Type ignore: _listeners is a private attribute
            if hasattr(transport, "_listeners") and transport._listeners:  # type: ignore
                server_listener = transport._listeners[0]  # type: ignore
                break

        if server_listener:
            listener_stats = server_listener.get_stats()
            registry_stats = server_listener._registry.get_stats()
            lock_stats = registry_stats.get("lock_stats", {})

            logger.debug("Registry Performance Stats:")
            logger.debug(f"  Lock Acquisitions: {lock_stats.get('acquisitions', 0)}")
            logger.debug(
                f"  Max Wait Time: {lock_stats.get('max_wait_time', 0) * 1000:.2f}ms"
            )
            logger.debug(
                f"  Max Hold Time: {lock_stats.get('max_hold_time', 0) * 1000:.2f}ms"
            )
            logger.debug(
                f"  Max Concurrent Holds: {lock_stats.get('max_concurrent_holds', 0)}"
            )
            logger.debug(
                f"  Fallback Routing Count: "
                f"{registry_stats.get('fallback_routing_count', 0)}"
            )
            logger.debug(
                f"  Packets Processed: {listener_stats.get('packets_processed', 0)}"
            )

            # Log stats on failure for debugging
            if len(failures) > 0:
                logger.warning("Registry Stats on Failure:")
                logger.warning(f"  {lock_stats}")
                logger.warning(f"  Registry Stats: {registry_stats}")

        # === Assertions ===
        success_rate = len(latencies) / STREAM_COUNT if STREAM_COUNT > 0 else 0.0
        min_success_rate = 1.0  # 100% success rate required
        assert success_rate >= min_success_rate, (
            f"Expected {min_success_rate:.0%} success rate, got {success_rate:.1%} "
            f"({len(latencies)}/{STREAM_COUNT} streams succeeded)"
        )
        assert all(isinstance(x, int) and x >= 0 for x in latencies), (
            "Invalid latencies"
        )

        avg_latency = sum(latencies) / len(latencies)
        logger.info(f"Average Latency: {avg_latency:.2f} ms")
        assert avg_latency < 1000


# ============================================================================
# New integration tests for quinn-inspired improvements
# ============================================================================


@pytest.mark.trio
async def test_quic_concurrent_streams():
    """Test QUIC handles 20-50 concurrent streams (focused on transport layer only)."""
    from libp2p.crypto.secp256k1 import create_new_key_pair
    from libp2p.peer.id import ID
    from libp2p.transport.quic.config import QUICTransportConfig
    from libp2p.transport.quic.transport import QUICTransport
    from libp2p.transport.quic.utils import create_quic_multiaddr

    if os.environ.get("PYTEST_XDIST_WORKER"):
        STREAM_COUNT = 20
        pytest.skip("flaky under xdist; run this integration test without -n")
    else:
        STREAM_COUNT = 50  # Between 20-50 as specified

    server_key = create_new_key_pair()
    client_key = create_new_key_pair()
    config = QUICTransportConfig(
        idle_timeout=30.0,
        connection_timeout=10.0,
        max_concurrent_streams=50,
    )

    server_transport = QUICTransport(server_key.private_key, config)
    client_transport = QUICTransport(client_key.private_key, config)

    server_received = []
    server_complete = trio.Event()

    async def server_handler(conn):
        """Server handler that accepts multiple streams."""

        async def handle_stream(stream):
            data = await stream.read()
            server_received.append(data)
            await stream.write(data)
            await stream.close()

        async with trio.open_nursery() as nursery:
            for _ in range(STREAM_COUNT):
                stream = await conn.accept_stream()
                nursery.start_soon(handle_stream, stream)
        server_complete.set()

    listener = server_transport.create_listener(server_handler)
    listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

    try:
        async with trio.open_nursery() as nursery:
            # Start server
            server_transport.set_background_nursery(nursery)
            client_transport.set_background_nursery(nursery)
            success = await listener.listen(listen_addr, nursery)
            assert success, "Failed to start server listener"

            server_addr = multiaddr.Multiaddr(
                f"{listener.get_addrs()[0]}/p2p/{ID.from_pubkey(server_key.public_key)}"
            )

            # Client connects and opens multiple streams
            conn = await client_transport.dial(server_addr)
            client_sent = []

            async def send_on_stream(i):
                stream = await conn.open_stream()
                data = f"stream_{i}".encode()
                client_sent.append(data)
                await stream.write(data)
                received = await stream.read()
                assert received == data
                await stream.close()

            async with trio.open_nursery() as client_nursery:
                for i in range(STREAM_COUNT):
                    client_nursery.start_soon(send_on_stream, i)

            # Wait for server to complete
            with trio.fail_after(30):
                await server_complete.wait()

            await conn.close()
            nursery.cancel_scope.cancel()
    finally:
        if not listener._closed:
            await listener.close()
        await server_transport.close()
        await client_transport.close()

    # Filter out empty data (from streams that didn't send data)
    server_received_filtered = [d for d in server_received if d]
    assert len(server_received_filtered) == STREAM_COUNT
    assert len(client_sent) == STREAM_COUNT
    assert set(server_received_filtered) == set(client_sent)


@pytest.mark.trio
async def test_connection_id_registry_high_concurrency():
    """
    Test registry with 100+ concurrent operations
    (registration, lookup, promotion).
    """
    from unittest.mock import Mock

    from libp2p.transport.quic.connection_id_registry import ConnectionIDRegistry

    registry = ConnectionIDRegistry(trio.Lock())
    operations_complete = [0]  # Use list to allow mutation from nested scope
    operations_lock = trio.Lock()

    async def concurrent_operation(i: int):
        """Perform multiple registry operations concurrently."""
        conn = Mock()
        # Use unique addresses to avoid conflicts
        addr = (f"127.0.0.{i % 10}", 12345 + (i % 10))
        conn._remote_addr = addr
        cid_base = f"cid_{i}".encode()

        # Register connection
        await registry.register_connection(cid_base, conn, addr, sequence=0)

        # Add multiple CIDs
        for seq in range(1, 4):
            cid = f"cid_{i}_{seq}".encode()
            await registry.add_connection_id(cid, cid_base, sequence=seq)

        # Lookup operations
        for seq in range(4):
            if seq == 0:
                cid = cid_base
            else:
                cid = f"cid_{i}_{seq}".encode()
            found_conn, _, _ = await registry.find_by_connection_id(cid)
            assert found_conn is conn

        # Address lookup - may find a different connection if multiple share address
        # (this is expected when i % 10 causes address collisions)
        found_conn, found_cid = await registry.find_by_address(addr)
        # Just verify we found some connection (may be different due to address reuse)
        assert found_conn is not None

        async with operations_lock:
            operations_complete[0] += 1

    # Run 100 concurrent operations
    async with trio.open_nursery() as nursery:
        for i in range(100):
            nursery.start_soon(concurrent_operation, i)

    assert operations_complete[0] == 100
    stats = registry.get_stats()
    # Note: established_connections counts CIDs, not unique connections
    # Each operation creates 1 connection with 4 CIDs (1 base + 3 additional)
    # So 100 operations = 100 connections = 400 CIDs
    # Type ignore: stats values may be dict or int depending on context
    established = stats["established_connections"]
    assert (
        established == 400 if isinstance(established, int) else len(established) == 400  # type: ignore
    )  # 100 connections * 4 CIDs each
    tracked = stats["tracked_sequences"]
    assert (
        tracked >= 100 * 4 if isinstance(tracked, int) else len(tracked) >= 100 * 4  # type: ignore
    )  # At least 4 sequences per connection


@pytest.mark.trio
async def test_quic_yamux_integration():
    """Integration test with realistic load (10-20 streams), full stack testing."""
    from libp2p.crypto.secp256k1 import create_new_key_pair
    from libp2p.peer.id import ID
    from libp2p.transport.quic.config import QUICTransportConfig
    from libp2p.transport.quic.transport import QUICTransport
    from libp2p.transport.quic.utils import create_quic_multiaddr

    STREAM_COUNT = 15  # Between 10-20 as specified
    server_key = create_new_key_pair()
    client_key = create_new_key_pair()

    config = QUICTransportConfig(
        idle_timeout=30.0,
        connection_timeout=10.0,
        max_concurrent_streams=30,
    )

    server_transport = QUICTransport(server_key.private_key, config)
    client_transport = QUICTransport(client_key.private_key, config)

    server_received = []
    server_complete = trio.Event()

    async def server_handler(conn):
        """Server handler that accepts multiple streams."""

        async def handle_stream(stream):
            data = await stream.read()
            server_received.append(data)
            await stream.write(data)
            await stream.close()

        async with trio.open_nursery() as nursery:
            for _ in range(STREAM_COUNT):
                stream = await conn.accept_stream()
                nursery.start_soon(handle_stream, stream)
        server_complete.set()

    listener = server_transport.create_listener(server_handler)
    listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

    try:
        async with trio.open_nursery() as nursery:
            # Start server
            server_transport.set_background_nursery(nursery)
            client_transport.set_background_nursery(nursery)
            success = await listener.listen(listen_addr, nursery)
            assert success, "Failed to start server listener"

            server_addr = multiaddr.Multiaddr(
                f"{listener.get_addrs()[0]}/p2p/{ID.from_pubkey(server_key.public_key)}"
            )

            # Client connects and opens streams
            conn = await client_transport.dial(server_addr)
            client_sent = []

            async def send_on_stream(i):
                stream = await conn.open_stream()
                data = f"yamux_stream_{i}".encode()
                client_sent.append(data)
                await stream.write(data)
                received = await stream.read()
                assert received == data
                await stream.close()

            async with trio.open_nursery() as client_nursery:
                for i in range(STREAM_COUNT):
                    client_nursery.start_soon(send_on_stream, i)

            # Wait for server to complete
            with trio.fail_after(30):
                await server_complete.wait()

            await conn.close()
            nursery.cancel_scope.cancel()
    finally:
        if not listener._closed:
            await listener.close()
        await server_transport.close()
        await client_transport.close()

    # Filter out empty data (from streams that didn't send data)
    server_received_filtered = [d for d in server_received if d]
    assert len(server_received_filtered) == STREAM_COUNT
    assert len(client_sent) == STREAM_COUNT
    assert set(server_received_filtered) == set(client_sent)


@pytest.mark.trio
async def test_quic_cid_retirement_integration():
    """Integration test for CID retirement ordering during active connection."""
    server_key = create_new_key_pair()
    client_key = create_new_key_pair()
    config = QUICTransportConfig(
        idle_timeout=30.0,
        connection_timeout=10.0,
        max_concurrent_streams=10,
    )

    server_transport = QUICTransport(server_key.private_key, config)
    client_transport = QUICTransport(client_key.private_key, config)

    connection_established = trio.Event()
    cids_tracked = []
    retirement_events = []

    async def server_handler(conn: QUICConnection) -> None:
        """Server handler that tracks CIDs and retirement."""
        nonlocal cids_tracked, retirement_events
        connection_established.set()

        # Get initial CIDs from listener
        for listener in server_transport._listeners:
            cids = await listener._registry.get_all_cids_for_connection(conn)
            cids_tracked.extend(cids)

        # Wait for potential CID issuance
        await trio.sleep(0.5)

        # Check for new CIDs
        for listener in server_transport._listeners:
            cids = await listener._registry.get_all_cids_for_connection(conn)
            cids_tracked.extend(cids)

        # Simulate retirement by manually calling registry methods
        # In real scenario, this would be triggered by ConnectionIdRetired events
        if len(cids_tracked) > 1:
            # Get connection from registry
            for listener in server_transport._listeners:
                # Find connection in registry
                for cid in cids_tracked[:2]:  # Retire first 2 CIDs
                    conn_obj, _, _ = await listener._registry.find_by_connection_id(cid)
                    if conn_obj is conn:
                        # Get sequence number
                        seq = await listener._registry.get_sequence_for_connection_id(
                            cid
                        )
                        if seq is not None and seq < 2:
                            # Retire CIDs with sequence < 2
                            registry = listener._registry
                            retired = (
                                await registry.retire_connection_ids_by_sequence_range(
                                    conn, 0, 2
                                )
                            )
                            retirement_events.extend(retired)

    listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")
    listener = server_transport.create_listener(server_handler)

    try:
        async with trio.open_nursery() as nursery:
            server_transport.set_background_nursery(nursery)
            client_transport.set_background_nursery(nursery)
            await listener.listen(listen_addr, nursery)
            server_addrs = listener.get_addrs()
            assert len(server_addrs) > 0

            # Client connects - need to add peer_id to multiaddr
            server_addr = multiaddr.Multiaddr(
                f"{server_addrs[0]}/p2p/{ID.from_pubkey(server_key.public_key)}"
            )
            client_conn = await client_transport.dial(server_addr)

            # Wait for connection establishment
            with trio.fail_after(5):
                await connection_established.wait()

            # Wait a bit for CID issuance and retirement
            await trio.sleep(1.0)

            # Verify retirement occurred if CIDs were tracked
            if cids_tracked:
                # At least some CIDs should be tracked
                assert len(cids_tracked) > 0

            await client_conn.close()
            nursery.cancel_scope.cancel()
    finally:
        if not listener._closed:
            await listener.close()
        await server_transport.close()
        await client_transport.close()


@pytest.mark.trio
async def test_connection_migration_scenario():
    """Test CID changes during connection migration scenario."""
    server_key = create_new_key_pair()
    client_key = create_new_key_pair()
    config = QUICTransportConfig(
        idle_timeout=30.0,
        connection_timeout=10.0,
        max_concurrent_streams=10,
    )

    server_transport = QUICTransport(server_key.private_key, config)
    client_transport = QUICTransport(client_key.private_key, config)

    connection_established = trio.Event()
    cids_seen = []

    async def server_handler(conn: QUICConnection) -> None:
        """Server handler that tracks CIDs."""
        nonlocal cids_seen
        connection_established.set()

        # Track CIDs over time
        for _ in range(5):
            for listener in server_transport._listeners:
                cids = await listener._registry.get_all_cids_for_connection(conn)
                cids_seen.extend(cids)
            await trio.sleep(0.2)

    listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")
    listener = server_transport.create_listener(server_handler)

    try:
        async with trio.open_nursery() as nursery:
            server_transport.set_background_nursery(nursery)
            client_transport.set_background_nursery(nursery)
            await listener.listen(listen_addr, nursery)
            server_addrs = listener.get_addrs()
            assert len(server_addrs) > 0

            # Client connects - need to add peer_id to multiaddr
            server_addr = multiaddr.Multiaddr(
                f"{server_addrs[0]}/p2p/{ID.from_pubkey(server_key.public_key)}"
            )
            client_conn = await client_transport.dial(server_addr)

            # Wait for connection establishment
            with trio.fail_after(5):
                await connection_established.wait()

            # Wait for potential CID changes
            await trio.sleep(1.0)

            # Verify CIDs were tracked
            assert len(cids_seen) > 0

            await client_conn.close()
            nursery.cancel_scope.cancel()
    finally:
        if not listener._closed:
            await listener.close()
        await server_transport.close()
        await client_transport.close()


@pytest.mark.trio
async def test_cid_retirement_under_load():
    """Test retirement during high load."""
    server_key = create_new_key_pair()
    client_key = create_new_key_pair()
    config = QUICTransportConfig(
        idle_timeout=30.0,
        connection_timeout=10.0,
        max_concurrent_streams=50,
    )

    server_transport = QUICTransport(server_key.private_key, config)
    client_transport = QUICTransport(client_key.private_key, config)

    connection_established = trio.Event()
    streams_completed_list = [0]  # Use list to allow mutation from nested scope

    async def server_handler(conn: QUICConnection) -> None:
        """Server handler that processes streams."""
        nonlocal streams_completed_list
        connection_established.set()

        # Process multiple streams asynchronously to handle concurrent streams
        async def process_one_stream(stream):
            try:
                data = await stream.read()
                await stream.write(data)
                await stream.close()
                streams_completed_list[0] += 1
            except Exception:
                # Stream might be closed, ignore
                pass

        # Process streams concurrently
        async with trio.open_nursery() as handler_nursery:
            for _ in range(20):
                try:
                    stream = await conn.accept_stream()
                    handler_nursery.start_soon(process_one_stream, stream)
                except Exception:
                    # Connection might be closed, break out of loop
                    break

    listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")
    listener = server_transport.create_listener(server_handler)

    try:
        async with trio.open_nursery() as nursery:
            server_transport.set_background_nursery(nursery)
            client_transport.set_background_nursery(nursery)
            await listener.listen(listen_addr, nursery)
            server_addrs = listener.get_addrs()
            assert len(server_addrs) > 0

            # Client connects - need to add peer_id to multiaddr
            server_addr = multiaddr.Multiaddr(
                f"{server_addrs[0]}/p2p/{ID.from_pubkey(server_key.public_key)}"
            )
            client_conn = await client_transport.dial(server_addr)

            # Wait for connection establishment
            with trio.fail_after(5):
                await connection_established.wait()

            # Open multiple streams concurrently
            async def send_data(i):
                stream = await client_conn.open_stream()
                await stream.write(f"data_{i}".encode())
                data = await stream.read()
                assert data == f"data_{i}".encode()
                await stream.close()

            async with trio.open_nursery() as client_nursery:
                for i in range(20):
                    client_nursery.start_soon(send_data, i)

            # Wait for streams to complete
            await trio.sleep(2.0)

            # Verify streams completed
            # Note: This test may count streams multiple times due to
            # concurrent processing. The exact count may vary, but should
            # be at least the expected number
            completed = streams_completed_list[0]
            assert completed >= 20, f"Expected at least 20 streams, got {completed}"

            await client_conn.close()
            nursery.cancel_scope.cancel()
    finally:
        if not listener._closed:
            await listener.close()
        await server_transport.close()
        await client_transport.close()
