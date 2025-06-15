"""
Enhanced NetStream Example for py-libp2p with State Management

This example demonstrates the new NetStream features including:
- State tracking and transitions
- Proper error handling and validation
- Resource cleanup and event notifications
- Thread-safe operations with Trio locks

Based on the standard echo demo but enhanced to show NetStream state management.
"""

import argparse
import random
import secrets

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.stream.exceptions import (
    StreamClosed,
    StreamEOF,
    StreamReset,
)
from libp2p.network.stream.net_stream import (
    NetStream,
    StreamState,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)

PROTOCOL_ID = TProtocol("/echo/1.0.0")


async def enhanced_echo_handler(stream: NetStream) -> None:
    """
    Enhanced echo handler that demonstrates NetStream state management.
    """
    print(f"New connection established: {stream}")
    print(f"Initial stream state: {await stream.state}")

    try:
        # Verify stream is in expected initial state
        assert await stream.state == StreamState.OPEN
        assert await stream.is_readable()
        assert await stream.is_writable()
        print("✓ Stream initialized in OPEN state")

        # Read incoming data with proper state checking
        print("Waiting for client data...")

        while await stream.is_readable():
            try:
                # Read data from client
                data = await stream.read(1024)
                if not data:
                    print("Received empty data, client may have closed")
                    break

                print(f"Received: {data.decode('utf-8').strip()}")

                # Check if we can still write before echoing
                if await stream.is_writable():
                    await stream.write(data)
                    print(f"Echoed: {data.decode('utf-8').strip()}")
                else:
                    print("Cannot echo - stream not writable")
                    break

            except StreamEOF:
                print("Client closed their write side (EOF)")
                break
            except StreamReset:
                print("Stream was reset by client")
                return
            except StreamClosed as e:
                print(f"Stream operation failed: {e}")
                break

        # Demonstrate graceful closure
        current_state = await stream.state
        print(f"Current state before close: {current_state}")

        if current_state not in [StreamState.CLOSE_BOTH, StreamState.RESET]:
            await stream.close()
            print("Server closed write side")

        final_state = await stream.state
        print(f"Final stream state: {final_state}")

    except Exception as e:
        print(f"Handler error: {e}")
        # Reset stream on unexpected errors
        if await stream.state not in [StreamState.RESET, StreamState.CLOSE_BOTH]:
            await stream.reset()
            print("Stream reset due to error")


async def enhanced_client_demo(stream: NetStream) -> None:
    """
    Enhanced client that demonstrates various NetStream state scenarios.
    """
    print(f"Client stream established: {stream}")
    print(f"Initial state: {await stream.state}")

    try:
        # Verify initial state
        assert await stream.state == StreamState.OPEN
        print("✓ Client stream in OPEN state")

        # Scenario 1: Normal communication
        message = b"Hello from enhanced NetStream client!\n"

        if await stream.is_writable():
            await stream.write(message)
            print(f"Sent: {message.decode('utf-8').strip()}")
        else:
            print("Cannot write - stream not writable")
            return

        # Close write side to signal EOF to server
        await stream.close()
        print("Client closed write side")

        # Verify state transition
        state_after_close = await stream.state
        print(f"State after close: {state_after_close}")
        assert state_after_close == StreamState.CLOSE_WRITE
        assert await stream.is_readable()  # Should still be readable
        assert not await stream.is_writable()  # Should not be writable

        # Try to write (should fail)
        try:
            await stream.write(b"This should fail")
            print("ERROR: Write succeeded when it should have failed!")
        except StreamClosed as e:
            print(f"✓ Expected error when writing to closed stream: {e}")

        # Read the echo response
        if await stream.is_readable():
            try:
                response = await stream.read()
                print(f"Received echo: {response.decode('utf-8').strip()}")
            except StreamEOF:
                print("Server closed their write side")
            except StreamReset:
                print("Stream was reset")

        # Check final state
        final_state = await stream.state
        print(f"Final client state: {final_state}")

    except Exception as e:
        print(f"Client error: {e}")
        # Reset on error
        await stream.reset()
        print("Client reset stream due to error")


async def run_enhanced_demo(
    port: int, destination: str, seed: int | None = None
) -> None:
    """
    Run enhanced echo demo with NetStream state management.
    """
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    # Generate or use provided key
    if seed:
        random.seed(seed)
        secret_number = random.getrandbits(32 * 8)
        secret = secret_number.to_bytes(length=32, byteorder="big")
    else:
        secret = secrets.token_bytes(32)

    host = new_host(key_pair=create_new_key_pair(secret))

    async with host.run(listen_addrs=[listen_addr]):
        print(f"Host ID: {host.get_id().to_string()}")
        print("=" * 60)

        if not destination:  # Server mode
            print("🖥️  ENHANCED ECHO SERVER MODE")
            print("=" * 60)

            # type: ignore: Stream is type of NetStream
            host.set_stream_handler(PROTOCOL_ID, enhanced_echo_handler)

            print(
                "Run client from another console:\n"
                f"python3 example_net_stream.py "
                f"-d {host.get_addrs()[0]}\n"
            )
            print("Waiting for connections...")
            print("Press Ctrl+C to stop server")
            await trio.sleep_forever()

        else:  # Client mode
            print("📱 ENHANCED ECHO CLIENT MODE")
            print("=" * 60)

            # Connect to server
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            await host.connect(info)
            print(f"Connected to server: {info.peer_id.pretty()}")

            # Create stream and run enhanced demo
            stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])
            if isinstance(stream, NetStream):
                await enhanced_client_demo(stream)

            print("\n" + "=" * 60)
            print("CLIENT DEMO COMPLETE")


def main() -> None:
    example_maddr = (
        "/ip4/127.0.0.1/tcp/8000/p2p/QmQn4SwGkDZKkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
    )

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-p", "--port", default=0, type=int, help="source port number")
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help=f"destination multiaddr string, e.g. {example_maddr}",
    )
    parser.add_argument(
        "-s",
        "--seed",
        type=int,
        help="seed for deterministic peer ID generation",
    )
    parser.add_argument(
        "--demo-states", action="store_true", help="run state transition demo only"
    )

    args = parser.parse_args()

    try:
        trio.run(run_enhanced_demo, args.port, args.destination, args.seed)
    except KeyboardInterrupt:
        print("\n👋 Demo interrupted by user")
    except Exception as e:
        print(f"❌ Demo failed: {e}")


if __name__ == "__main__":
    main()
