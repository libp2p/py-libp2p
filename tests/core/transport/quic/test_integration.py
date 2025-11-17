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

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p.transport.quic").setLevel(logging.DEBUG)
logging.getLogger("libp2p.host").setLevel(logging.DEBUG)
logging.getLogger("libp2p.network").setLevel(logging.DEBUG)
logging.getLogger("libp2p.protocol_muxer").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


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
        print("\n=== BASIC QUIC ECHO TEST ===")

        # Create server components
        server_transport = QUICTransport(server_key.private_key, server_config)

        # Track test state
        server_received_data = None
        server_connection_established = False
        echo_sent = False

        async def echo_server_handler(connection: QUICConnection) -> None:
            """Simple echo server handler with detailed logging."""
            nonlocal server_received_data, server_connection_established, echo_sent

            print("🔗 SERVER: Connection handler called")
            server_connection_established = True

            try:
                print("📡 SERVER: Waiting for incoming stream...")

                # Accept stream with timeout and detailed logging
                print("📡 SERVER: Calling accept_stream...")
                stream = await connection.accept_stream(timeout=5.0)

                if stream is None:
                    print("❌ SERVER: accept_stream returned None")
                    return

                print(f"✅ SERVER: Stream accepted! Stream ID: {stream.stream_id}")

                # Read data from the stream
                print("📖 SERVER: Reading data from stream...")
                server_data = await stream.read(1024)

                if not server_data:
                    print("❌ SERVER: No data received from stream")
                    return

                server_received_data = server_data.decode("utf-8", errors="ignore")
                print(f"📨 SERVER: Received data: '{server_received_data}'")

                # Echo the data back
                echo_message = f"ECHO: {server_received_data}"
                print(f"📤 SERVER: Sending echo: '{echo_message}'")

                await stream.write(echo_message.encode())
                echo_sent = True
                print("✅ SERVER: Echo sent successfully")

                # Close the stream
                await stream.close()
                print("🔒 SERVER: Stream closed")

            except Exception as e:
                print(f"❌ SERVER: Error in handler: {e}")
                import traceback

                traceback.print_exc()

        # Create listener
        listener = server_transport.create_listener(echo_server_handler)
        listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")

        # Variables to track client state
        client_connected = False
        client_sent_data = False
        client_received_echo = None

        try:
            print("🚀 Starting server...")

            async with trio.open_nursery() as nursery:
                # Start server listener
                success = await listener.listen(listen_addr, nursery)
                assert success, "Failed to start server listener"

                # Get server address
                server_addrs = listener.get_addrs()
                server_addr = multiaddr.Multiaddr(
                    f"{server_addrs[0]}/p2p/{ID.from_pubkey(server_key.public_key)}"
                )
                print(f"🔧 SERVER: Listening on {server_addr}")

                # Give server a moment to be ready
                await trio.sleep(0.1)

                print("🚀 Starting client...")

                # Create client transport
                client_transport = QUICTransport(client_key.private_key, client_config)
                client_transport.set_background_nursery(nursery)

                try:
                    # Connect to server
                    print(f"📞 CLIENT: Connecting to {server_addr}")
                    connection = await client_transport.dial(server_addr)
                    client_connected = True
                    print("✅ CLIENT: Connected to server")

                    # Open a stream
                    print("📤 CLIENT: Opening stream...")
                    stream = await connection.open_stream()
                    print(f"✅ CLIENT: Stream opened with ID: {stream.stream_id}")

                    # Send test data
                    test_message = "Hello QUIC Server!"
                    print(f"📨 CLIENT: Sending message: '{test_message}'")
                    await stream.write(test_message.encode())
                    client_sent_data = True
                    print("✅ CLIENT: Message sent")

                    # Read echo response
                    print("📖 CLIENT: Waiting for echo response...")
                    response_data = await stream.read(1024)

                    if response_data:
                        client_received_echo = response_data.decode(
                            "utf-8", errors="ignore"
                        )
                        print(f"📬 CLIENT: Received echo: '{client_received_echo}'")
                    else:
                        print("❌ CLIENT: No echo response received")

                    print("🔒 CLIENT: Closing connection")
                    await connection.close()
                    print("🔒 CLIENT: Connection closed")

                    print("🔒 CLIENT: Closing transport")
                    await client_transport.close()
                    print("🔒 CLIENT: Transport closed")

                except Exception as e:
                    print(f"❌ CLIENT: Error: {e}")
                    import traceback

                    traceback.print_exc()

                finally:
                    await client_transport.close()
                    print("🔒 CLIENT: Transport closed")

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
        print("\n📊 TEST RESULTS:")
        print(f"   Server connection established: {server_connection_established}")
        print(f"   Client connected: {client_connected}")
        print(f"   Client sent data: {client_sent_data}")
        print(f"   Server received data: '{server_received_data}'")
        print(f"   Echo sent by server: {echo_sent}")
        print(f"   Client received echo: '{client_received_echo}'")

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

        print("✅ BASIC ECHO TEST PASSED!")

    @pytest.mark.trio
    async def test_server_accept_stream_timeout(
        self, server_key, client_key, server_config, client_config
    ):
        """Test what happens when server accept_stream times out."""
        print("\n=== TESTING SERVER ACCEPT_STREAM TIMEOUT ===")

        server_transport = QUICTransport(server_key.private_key, server_config)

        accept_stream_called = False
        accept_stream_timeout = False

        async def timeout_test_handler(connection: QUICConnection) -> None:
            """Handler that tests accept_stream timeout."""
            nonlocal accept_stream_called, accept_stream_timeout

            print("🔗 SERVER: Connection established, testing accept_stream timeout")
            accept_stream_called = True

            try:
                print("📡 SERVER: Calling accept_stream with 2 second timeout...")
                stream = await connection.accept_stream(timeout=2.0)
                print(f"✅ SERVER: accept_stream returned: {stream}")

            except Exception as e:
                print(f"⏰ SERVER: accept_stream timed out or failed: {e}")
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
                print(f"🔧 SERVER: Listening on {server_addr}")

                # Start client in the same nursery
                client_transport = QUICTransport(client_key.private_key, client_config)
                client_transport.set_background_nursery(nursery)

                connection = None
                try:
                    print("📞 CLIENT: Connecting (but NOT opening stream)...")
                    connection = await client_transport.dial(server_addr)
                    print("✅ CLIENT: Connected (no stream opened)")

                    # Wait for server timeout
                    await trio.sleep(3.0)

                finally:
                    await client_transport.close()
                    if connection:
                        await connection.close()
                        print("🔒 CLIENT: Connection closed")

                nursery.cancel_scope.cancel()

        finally:
            if client_transport and not client_transport._closed:
                await client_transport.close()
            if not listener._closed:
                await listener.close()
            if not server_transport._closed:
                await server_transport.close()

        print("\n📊 TIMEOUT TEST RESULTS:")
        print(f"   accept_stream called: {accept_stream_called}")
        print(f"   accept_stream timeout: {accept_stream_timeout}")

        assert accept_stream_called, "accept_stream should have been called"
        assert accept_stream_timeout, (
            "accept_stream should have timed out when no stream was opened"
        )

        print("✅ TIMEOUT TEST PASSED!")


@pytest.mark.trio
@pytest.mark.flaky(reruns=3, reruns_delay=2)
async def test_yamux_stress_ping():
    STREAM_COUNT = 100
    listen_addr = create_quic_multiaddr("127.0.0.1", 0, "/quic")
    latencies = []
    failures = []
    completion_event = trio.Event()
    completed_count: list[int] = [0]  # Use list to make it mutable for closures
    completed_lock = trio.Lock()

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
            await client_host.connect(info)

            # Wait for connection to be established and ready
            # (check actual connection state)
            network = client_host.get_network()
            connections_map = network.get_connections_map()
            while (
                info.peer_id not in connections_map or not connections_map[info.peer_id]
            ):
                await trio.sleep(0.01)
                connections_map = network.get_connections_map()

            # Wait for connection's event_started to ensure it's ready for streams
            # This ensures the muxer is fully initialized and can accept streams
            connections = connections_map[info.peer_id]
            if connections:
                swarm_conn = connections[0]
                # Wait for the connection to be fully started (muxer ready)
                if hasattr(swarm_conn, "event_started"):
                    await swarm_conn.event_started.wait()
                # Additional small wait to ensure multiselect is ready
                await trio.sleep(0.05)

            async def ping_stream(i: int):
                stream = None
                try:
                    start = trio.current_time()

                    stream = await client_host.new_stream(
                        info.peer_id, [PING_PROTOCOL_ID]
                    )

                    await stream.write(b"\x01" * PING_LENGTH)

                    # Wait for response with timeout as safety net
                    with trio.fail_after(30):
                        response = await stream.read(PING_LENGTH)

                    if response == b"\x01" * PING_LENGTH:
                        latency_ms = int((trio.current_time() - start) * 1000)
                        latencies.append(latency_ms)
                        print(f"[Ping #{i}] Latency: {latency_ms} ms")
                    await stream.close()
                except Exception as e:
                    print(f"[Ping #{i}] Failed: {e}")
                    failures.append(i)
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

            # Use a semaphore to limit concurrent stream openings
            # NOTE: This is a TEST-ONLY workaround, not a real connection limit.
            # The QUIC connection itself supports up to 1000 concurrent streams
            # (MAX_OUTGOING_STREAMS). However, opening 100 streams simultaneously
            # in a stress test can cause transient failures due to:
            # - Protocol negotiation timeouts (multiselect) - the default 5s timeout
            #   may be insufficient when 20+ streams negotiate simultaneously
            # - Resource contention during stream creation
            # - Race conditions in the stream opening path
            # The semaphore throttles concurrent openings to make the test more
            # reliable. Real applications don't need this - they naturally throttle
            # based on their needs, and the connection handles the actual limits.
            # WHY IT FAILS THE FIRST TIME: Even with the semaphore, there's still
            # contention on multiselect negotiation. When many streams try to
            # negotiate at once, some may timeout. The @pytest.mark.flaky decorator
            # handles this by retrying the test automatically.
            semaphore = trio.Semaphore(15)  # Max 15 concurrent stream openings

            async def ping_stream_with_semaphore(i: int):
                async with semaphore:
                    await ping_stream(i)

            async with trio.open_nursery() as nursery:
                for i in range(STREAM_COUNT):
                    nursery.start_soon(ping_stream_with_semaphore, i)

                # Wait for all streams to complete (event-driven, not polling)
                with trio.fail_after(120):  # Safety timeout
                    await completion_event.wait()

        # === Result Summary ===
        print("\n📊 Ping Stress Test Summary")
        print(f"Total Streams Launched: {STREAM_COUNT}")
        print(f"Successful Pings: {len(latencies)}")
        print(f"Failed Pings: {len(failures)}")
        if failures:
            print(f"❌ Failed stream indices: {failures}")

        # === Assertions ===
        assert len(latencies) == STREAM_COUNT, (
            f"Expected {STREAM_COUNT} successful streams, got {len(latencies)}"
        )
        assert all(isinstance(x, int) and x >= 0 for x in latencies), (
            "Invalid latencies"
        )

        avg_latency = sum(latencies) / len(latencies)
        print(f"✅ Average Latency: {avg_latency:.2f} ms")
        assert avg_latency < 1000
