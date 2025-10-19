"""
Mplex Stream Timeout and Deadline Example

This example demonstrates the new timeout and deadline features in MplexStream,
including:
- Setting read and write deadlines
- Handling timeout errors
- Validating TTL values
- Demonstrating timeout behavior in real scenarios

Usage:
    python example_mplex_timeouts.py [--port PORT] [--destination DESTINATION]
"""

import argparse
import logging
import secrets

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.network.stream.exceptions import StreamEOF
from libp2p.network.stream.net_stream import INetStream, NetStream
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.insecure.transport import (
    PLAINTEXT_PROTOCOL_ID,
    InsecureTransport,
)
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.stream_muxer.mplex.mplex_stream import MplexStream
from libp2p.utils.address_validation import (
    find_free_port,
    get_available_interfaces,
    get_optimal_binding_address,
)

# Configure logging
logging.basicConfig(
    level=logging.ERROR,  # Start with ERROR level to suppress debug output
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mplex-timeouts")

# Suppress debug logging from libp2p components
logging.getLogger("multiaddr").setLevel(logging.ERROR)
logging.getLogger("libp2p").setLevel(logging.ERROR)
logging.getLogger("async_service").setLevel(logging.ERROR)

PROTOCOL_ID = TProtocol("/timeout-demo/1.0.0")
TEST_MESSAGE = b"Hello, timeout world!"


async def timeout_demo_handler(stream: INetStream) -> None:
    """Handler that demonstrates timeout behavior on the server side."""
    try:
        # Cast to NetStream to access muxed_conn and muxed_stream attributes
        net_stream: NetStream = stream  # type: ignore[assignment]

        peer_id = net_stream.muxed_conn.peer_id
        print(f"📥 Received connection from {peer_id}")

        # Get the underlying mplex stream
        mplex_stream: MplexStream = net_stream.muxed_stream  # type: ignore[assignment]

        # Demonstrate server-side timeout handling
        print("🕐 Server: Setting 3-second read deadline...")
        success = mplex_stream.set_read_deadline(3)
        print(f"   Deadline set: {'✅ Success' if success else '❌ Failed'}")

        # Try to read with timeout
        try:
            data = await stream.read(len(TEST_MESSAGE))
            print(f"📤 Server received: {data.decode('utf-8')}")

            # Set write deadline and respond
            print("🕐 Server: Setting 2-second write deadline...")
            success = mplex_stream.set_write_deadline(2)
            print(f"   Deadline set: {'✅ Success' if success else '❌ Failed'}")

            response = b"Server response: " + data
            await stream.write(response)
            print(f"📤 Server sent: {response.decode('utf-8')}")

        except TimeoutError as e:
            print(f"⏰ Server read timeout: {e}")
            await stream.write(b"Server timeout occurred")

    except StreamEOF:
        print("📤 Client disconnected")
    except Exception as e:
        print(f"❌ Server error: {e}")
    finally:
        await stream.close()


async def demonstrate_deadline_validation(stream: INetStream) -> None:
    """Demonstrate the new deadline validation features."""
    print("\n🔍 Testing Deadline Validation Features:")

    # Cast to NetStream to access muxed_stream attribute
    net_stream: NetStream = stream  # type: ignore[assignment]
    mplex_stream: MplexStream = net_stream.muxed_stream  # type: ignore[assignment]

    # Test negative TTL (should return False)
    print("   Testing negative TTL...")
    result = mplex_stream.set_read_deadline(-1)
    expected = "✅ False (expected)" if not result else "❌ True (unexpected)"
    print(f"   set_read_deadline(-1): {expected}")

    result = mplex_stream.set_write_deadline(-5)
    expected = "✅ False (expected)" if not result else "❌ True (unexpected)"
    print(f"   set_write_deadline(-5): {expected}")

    # Test zero TTL (should return True)
    print("   Testing zero TTL...")
    result = mplex_stream.set_read_deadline(0)
    expected = "✅ True (expected)" if result else "❌ False (unexpected)"
    print(f"   set_read_deadline(0): {expected}")

    # Test positive TTL (should return True)
    print("   Testing positive TTL...")
    result = mplex_stream.set_read_deadline(5)
    expected = "✅ True (expected)" if result else "❌ False (unexpected)"
    print(f"   set_read_deadline(5): {expected}")

    # Test set_deadline (both read and write)
    print("   Testing set_deadline...")
    result = mplex_stream.set_deadline(10)
    expected = "✅ True (expected)" if result else "❌ False (unexpected)"
    print(f"   set_deadline(10): {expected}")


async def demonstrate_timeout_scenarios(stream: INetStream) -> None:
    """Demonstrate different timeout scenarios."""
    print("\n⏰ Testing Timeout Scenarios:")

    # Cast to NetStream to access muxed_stream attribute
    net_stream: NetStream = stream  # type: ignore[assignment]
    mplex_stream: MplexStream = net_stream.muxed_stream  # type: ignore[assignment]

    # Scenario 1: Normal operation with timeout
    print("   Scenario 1: Normal operation with 5-second timeout...")
    success = mplex_stream.set_read_deadline(5)
    if success:
        try:
            await stream.write(TEST_MESSAGE)
            print(f"   📤 Sent: {TEST_MESSAGE.decode('utf-8')}")

            response = await stream.read(1024)
            print(f"   📥 Received: {response.decode('utf-8')}")
            print("   ✅ Normal operation completed successfully")
        except TimeoutError as e:
            print(f"   ⏰ Timeout occurred: {e}")

    # Scenario 2: Very short timeout (likely to timeout)
    print("   Scenario 2: Very short timeout (0 seconds)...")
    success = mplex_stream.set_read_deadline(0)
    if success:
        try:
            # Try to read with very short timeout
            await stream.read(1024)
            print("   ✅ Unexpected: Read completed within 0 seconds")
        except TimeoutError as e:
            print(f"   ⏰ Expected timeout: {e}")

    # Scenario 3: Write timeout
    print("   Scenario 3: Write timeout test...")
    success = mplex_stream.set_write_deadline(0)
    if success:
        try:
            # Try to write with very short timeout
            large_data = b"X" * 10000  # Large data that might take time
            await stream.write(large_data)
            print("   ✅ Write completed within timeout")
        except TimeoutError as e:
            print(f"   ⏰ Write timeout: {e}")


async def run_server(port: int) -> None:
    """Run the timeout demo server."""
    print("🚀 Starting Mplex Timeout Demo Server...")

    # Create key pair and security transport
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    insecure_transport = InsecureTransport(
        local_key_pair=key_pair,
        secure_bytes_provider=None,
        peerstore=None,
    )

    security_options = {PLAINTEXT_PROTOCOL_ID: insecure_transport}

    # Create host with explicit mplex configuration
    host = new_host(
        key_pair=key_pair,
        sec_opt=security_options,
        muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
    )

    # Set up stream handler
    host.set_stream_handler(PROTOCOL_ID, timeout_demo_handler)

    # Configure listening address
    if port == 0:
        port = find_free_port()

    listen_addrs = get_available_interfaces(port)
    optimal_addr = get_optimal_binding_address(port)

    print(f"🔗 Server listening on port {port}")
    print(f"📍 Optimal address: {optimal_addr}")

    async with host.run(listen_addrs=listen_addrs):
        print("✅ Server ready and listening for connections...")

        # Get the server's peer ID and create the full destination address
        server_addrs = host.get_addrs()
        if server_addrs:
            # Use the first address and add the peer ID
            server_addr = str(server_addrs[0])
            server_peer_id = host.get_id().to_string()
            # Check if the address already has a p2p part
            if "/p2p/" in server_addr:
                full_destination = server_addr
            else:
                full_destination = f"{server_addr}/p2p/{server_peer_id}"

            print("\n📋 To connect a client, run:")
            print(
                f"python example_mplex_timeouts.py --role client "
                f"--destination {full_destination}"
            )
            print("\n   Or with verbose logging:")
            print(
                f"python example_mplex_timeouts.py --role client "
                f"--destination {full_destination} --verbose"
            )
            print("\n🔄 Server is running... Press Ctrl+C to stop")
        else:
            print("❌ Failed to get server addresses")

        # Keep server running
        await trio.sleep_forever()


async def run_client(destination: str) -> None:
    """Run the timeout demo client."""
    print("🚀 Starting Mplex Timeout Demo Client...")

    # Create key pair and security transport
    secret = secrets.token_bytes(32)
    key_pair = create_new_key_pair(secret)

    insecure_transport = InsecureTransport(
        local_key_pair=key_pair,
        secure_bytes_provider=None,
        peerstore=None,
    )

    security_options = {PLAINTEXT_PROTOCOL_ID: insecure_transport}

    # Create host with explicit mplex configuration
    host = new_host(
        key_pair=key_pair,
        sec_opt=security_options,
        muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
    )

    # Parse destination address
    maddr = multiaddr.Multiaddr(destination)
    info = info_from_p2p_addr(maddr)

    async with host.run(listen_addrs=[]):
        print(f"🔗 Connecting to {info.peer_id} at {maddr}")

        try:
            # Connect to server
            await host.connect(info)
            print("✅ Connected to server")

            # Open stream
            stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])
            print("✅ Stream opened")

            # Demonstrate deadline validation
            await demonstrate_deadline_validation(stream)

            # Demonstrate timeout scenarios
            await demonstrate_timeout_scenarios(stream)

            # Clean up
            await stream.close()
            print("✅ Stream closed")

        except Exception as e:
            print(f"❌ Client error: {e}")

        print("🏁 Client demo completed")


async def main(role: str, port: int, destination: str | None) -> None:
    """Main function to run the timeout demo."""
    if role == "client":
        if not destination:
            print("❌ Error: --destination is required for client role")
            return
        await run_client(destination)
    elif role == "server":
        await run_server(port)
    else:
        print(f"❌ Error: Invalid role '{role}'. Must be 'server' or 'client'")


def create_parser() -> argparse.ArgumentParser:
    """Create command line argument parser."""
    parser = argparse.ArgumentParser(
        description="""
        Mplex Stream Timeout and Deadline Demo

        This example demonstrates the new timeout and deadline features in MplexStream:
        - Setting read and write deadlines with validation
        - Handling timeout errors gracefully
        - Demonstrating timeout behavior in real scenarios

        Usage:
        1. Start server: python example_mplex_timeouts.py --role server --port 8000
        2. Start client: python example_mplex_timeouts.py --role client
           --destination <server_address>

        The demo will show:
        - Deadline validation (negative, zero, positive TTL values)
        - Timeout scenarios with different deadline settings
        - Error handling for timeout conditions
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--role",
        type=str,
        choices=["server", "client"],
        required=True,
        help="Role to run as: 'server' or 'client'",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for server to listen on (default: 8000, 0 for random)",
    )

    parser.add_argument(
        "--destination",
        type=str,
        help="Server multiaddr to connect to (required for client role)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser


if __name__ == "__main__":
    parser = create_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
        logger.setLevel(logging.INFO)
        # Re-enable debug logging for libp2p components when verbose
        logging.getLogger("multiaddr").setLevel(logging.DEBUG)
        logging.getLogger("libp2p").setLevel(logging.DEBUG)
        logging.getLogger("async_service").setLevel(logging.DEBUG)
        print("🔍 Verbose logging enabled")

    try:
        trio.run(main, args.role, args.port, args.destination)
    except KeyboardInterrupt:
        print("👋 Demo interrupted by user")
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        raise
