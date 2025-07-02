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
import trio

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.transport import QUICTransport
from libp2p.transport.quic.utils import create_quic_multiaddr

# Set up logging to see what's happening
logging.basicConfig(level=logging.DEBUG)
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
                server_addr = server_addrs[0]
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

        client_connected = False

        try:
            async with trio.open_nursery() as nursery:
                # Start server
                server_transport.set_background_nursery(nursery)
                success = await listener.listen(listen_addr, nursery)
                assert success

                server_addr = listener.get_addrs()[0]
                print(f"🔧 SERVER: Listening on {server_addr}")

                # Create client but DON'T open a stream
                async with trio.open_nursery() as client_nursery:
                    client_transport = QUICTransport(
                        client_key.private_key, client_config
                    )
                    client_transport.set_background_nursery(client_nursery)

                    try:
                        print("📞 CLIENT: Connecting (but NOT opening stream)...")
                        connection = await client_transport.dial(server_addr)
                        client_connected = True
                        print("✅ CLIENT: Connected (no stream opened)")

                        # Wait for server timeout
                        await trio.sleep(3.0)

                        await connection.close()
                        print("🔒 CLIENT: Connection closed")

                    finally:
                        await client_transport.close()

                nursery.cancel_scope.cancel()

        finally:
            await listener.close()
            await server_transport.close()

        print("\n📊 TIMEOUT TEST RESULTS:")
        print(f"   Client connected: {client_connected}")
        print(f"   accept_stream called: {accept_stream_called}")
        print(f"   accept_stream timeout: {accept_stream_timeout}")

        assert client_connected, "Client should have connected"
        assert accept_stream_called, "accept_stream should have been called"
        assert accept_stream_timeout, (
            "accept_stream should have timed out when no stream was opened"
        )

        print("✅ TIMEOUT TEST PASSED!")
