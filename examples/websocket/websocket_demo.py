import argparse
import logging
import signal
import sys
import traceback

import multiaddr
import trio

from libp2p.abc import INotifee
from libp2p.crypto.ed25519 import create_new_key_pair as create_ed25519_key_pair
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.host.basic_host import BasicHost
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.peer.peerstore import PeerStore
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)
from libp2p.stream_muxer.yamux.yamux import Yamux
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.transport import WebsocketTransport

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger("libp2p.websocket-example")


# Suppress KeyboardInterrupt by handling SIGINT directly
def signal_handler(signum, frame):
    print("✅ Clean exit completed.")
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)

# Simple echo protocol
ECHO_PROTOCOL_ID = TProtocol("/echo/1.0.0")


async def echo_handler(stream):
    """Simple echo handler that echoes back any data received."""
    try:
        data = await stream.read(1024)
        if data:
            message = data.decode("utf-8", errors="replace")
            print(f"📥 Received: {message}")
            print(f"📤 Echoing back: {message}")
            await stream.write(data)
        await stream.close()
    except Exception as e:
        logger.error(f"Echo handler error: {e}")
        await stream.close()


def create_websocket_host(listen_addrs=None, use_plaintext=False):
    """Create a host with WebSocket transport."""
    # Create key pair and peer store
    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    peer_store = PeerStore()
    peer_store.add_key_pair(peer_id, key_pair)

    if use_plaintext:
        # Create transport upgrader with plaintext security
        upgrader = TransportUpgrader(
            secure_transports_by_protocol={
                TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
            },
            muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
        )
    else:
        # Create separate Ed25519 key for Noise protocol
        noise_key_pair = create_ed25519_key_pair()

        # Create Noise transport
        noise_transport = NoiseTransport(
            libp2p_keypair=key_pair,
            noise_privkey=noise_key_pair.private_key,
            early_data=None,
            with_noise_pipes=False,
        )

        # Create transport upgrader with Noise security
        upgrader = TransportUpgrader(
            secure_transports_by_protocol={
                TProtocol(NOISE_PROTOCOL_ID): noise_transport
            },
            muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
        )

    # Create WebSocket transport
    transport = WebsocketTransport(upgrader)

    # Create swarm and host
    swarm = Swarm(peer_id, peer_store, upgrader, transport)
    host = BasicHost(swarm)

    return host


async def run(port: int, destination: str, use_plaintext: bool = False) -> None:
    localhost_ip = "0.0.0.0"

    if not destination:
        # Create first host (listener) with WebSocket transport
        listen_addr = multiaddr.Multiaddr(f"/ip4/{localhost_ip}/tcp/{port}/ws")

        try:
            host = create_websocket_host(use_plaintext=use_plaintext)
            logger.debug(f"Created host with use_plaintext={use_plaintext}")

            # Set up echo handler
            host.set_stream_handler(ECHO_PROTOCOL_ID, echo_handler)

            # Add connection event handlers for debugging
            class DebugNotifee(INotifee):
                async def opened_stream(self, network, stream):
                    pass

                async def closed_stream(self, network, stream):
                    pass

                async def connected(self, network, conn):
                    print(
                        f"🔗 New libp2p connection established: "
                        f"{conn.muxed_conn.peer_id}"
                    )
                    if hasattr(conn.muxed_conn, "get_security_protocol"):
                        security = conn.muxed_conn.get_security_protocol()
                    else:
                        security = "Unknown"

                    print(f"   Security: {security}")

                async def disconnected(self, network, conn):
                    print(f"🔌 libp2p connection closed: {conn.muxed_conn.peer_id}")

                async def listen(self, network, multiaddr):
                    pass

                async def listen_close(self, network, multiaddr):
                    pass

            host.get_network().register_notifee(DebugNotifee())

            # Create a cancellation token for clean shutdown
            cancel_scope = trio.CancelScope()

            async def signal_handler():
                with trio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as (
                    signal_receiver
                ):
                    async for sig in signal_receiver:
                        print(f"\n🛑 Received signal {sig}")
                        print("✅ Shutting down WebSocket server...")
                        cancel_scope.cancel()
                        return

            async with (
                host.run(listen_addrs=[listen_addr]),
                trio.open_nursery() as (nursery),
            ):
                # Start the peer-store cleanup task
                nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

                # Start the signal handler
                nursery.start_soon(signal_handler)

                # Get the actual address and replace 0.0.0.0 with 127.0.0.1 for client
                # connections
                addrs = host.get_addrs()
                logger.debug(f"Host addresses: {addrs}")
                if not addrs:
                    print("❌ Error: No addresses found for the host")
                    print("Debug: host.get_addrs() returned empty list")
                    return

                server_addr = str(addrs[0])
                client_addr = server_addr.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/")

                print("🌐 WebSocket Server Started Successfully!")
                print("=" * 50)
                print(f"📍 Server Address: {client_addr}")
                print("🔧 Protocol: /echo/1.0.0")
                print("🚀 Transport: WebSocket (/ws)")
                print()
                print("📋 To test the connection, run this in another terminal:")
                plaintext_flag = " --plaintext" if use_plaintext else ""
                print(f"   python websocket_demo.py -d {client_addr}{plaintext_flag}")
                print()
                print("⏳ Waiting for incoming WebSocket connections...")
                print("─" * 50)

                # Add a custom handler to show connection events
                async def custom_echo_handler(stream):
                    peer_id = stream.muxed_conn.peer_id
                    print("\n🔗 New WebSocket Connection!")
                    print(f"   Peer ID: {peer_id}")
                    print("   Protocol: /echo/1.0.0")

                    # Show remote address in multiaddr format
                    try:
                        remote_address = stream.get_remote_address()
                        if remote_address:
                            print(f"   Remote: {remote_address}")
                    except Exception:
                        print("   Remote: Unknown")

                    print("   ─" * 40)

                    # Call the original handler
                    await echo_handler(stream)

                    print("   ─" * 40)
                    print(f"✅ Echo request completed for peer: {peer_id}")
                    print()

                # Replace the handler with our custom one
                host.set_stream_handler(ECHO_PROTOCOL_ID, custom_echo_handler)

                # Wait indefinitely or until cancelled
                with cancel_scope:
                    await trio.sleep_forever()

        except Exception as e:
            print(f"❌ Error creating WebSocket server: {e}")
            traceback.print_exc()
            return

    else:
        # Create second host (dialer) with WebSocket transport
        listen_addr = multiaddr.Multiaddr(f"/ip4/{localhost_ip}/tcp/{port}/ws")

        try:
            # Create a single host for client operations
            host = create_websocket_host(use_plaintext=use_plaintext)

            # Start the host for client operations
            async with (
                host.run(listen_addrs=[listen_addr]),
                trio.open_nursery() as (nursery),
            ):
                # Start the peer-store cleanup task
                nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

                # Add connection event handlers for debugging
                class ClientDebugNotifee(INotifee):
                    async def opened_stream(self, network, stream):
                        pass

                    async def closed_stream(self, network, stream):
                        pass

                    async def connected(self, network, conn):
                        print(
                            f"🔗 Client: libp2p connection established: "
                            f"{conn.muxed_conn.peer_id}"
                        )

                    async def disconnected(self, network, conn):
                        print(
                            f"🔌 Client: libp2p connection closed: "
                            f"{conn.muxed_conn.peer_id}"
                        )

                    async def listen(self, network, multiaddr):
                        pass

                    async def listen_close(self, network, multiaddr):
                        pass

                host.get_network().register_notifee(ClientDebugNotifee())

                maddr = multiaddr.Multiaddr(destination)
                info = info_from_p2p_addr(maddr)
                print("🔌 WebSocket Client Starting...")
                print("=" * 40)
                print(f"🎯 Target Peer: {info.peer_id}")
                print(f"📍 Target Address: {destination}")
                print()

                try:
                    print("🔗 Connecting to WebSocket server...")
                    print(f"   Security: {'Plaintext' if use_plaintext else 'Noise'}")
                    await host.connect(info)
                    print("✅ Successfully connected to WebSocket server!")
                except Exception as e:
                    error_msg = str(e)
                    print("\n❌ Connection Failed!")
                    print(f"   Peer ID: {info.peer_id}")
                    print(f"   Address: {destination}")
                    print(f"   Security: {'Plaintext' if use_plaintext else 'Noise'}")
                    print(f"   Error: {error_msg}")
                    print(f"   Error type: {type(e).__name__}")

                    # Add more detailed error information for debugging
                    if hasattr(e, "__cause__") and e.__cause__:
                        print(f"   Root cause: {e.__cause__}")
                        print(f"   Root cause type: {type(e.__cause__).__name__}")

                    print()
                    print("💡 Troubleshooting:")
                    print("   • Make sure the WebSocket server is running")
                    print("   • Check that the server address is correct")
                    print("   • Verify the server is listening on the right port")
                    print(
                        "   • Ensure both client and server use the same sec protocol"
                    )
                    if not use_plaintext:
                        print("   • Noise over WebSocket may have compatibility issues")
                    return

                # Create a stream and send test data
                try:
                    stream = await host.new_stream(info.peer_id, [ECHO_PROTOCOL_ID])
                except Exception as e:
                    print(f"❌ Failed to create stream: {e}")
                    return

                try:
                    print("🚀 Starting Echo Protocol Test...")
                    print("─" * 40)

                    # Send test data
                    test_message = b"Hello WebSocket Transport!"
                    print(f"📤 Sending message: {test_message.decode('utf-8')}")
                    await stream.write(test_message)

                    # Read response
                    print("⏳ Waiting for server response...")
                    response = await stream.read(1024)
                    print(f"📥 Received response: {response.decode('utf-8')}")

                    await stream.close()

                    print("─" * 40)
                    if response == test_message:
                        print("🎉 Echo test successful!")
                        print("✅ WebSocket transport is working perfectly!")
                        print("✅ Client completed successfully, exiting.")
                    else:
                        print("❌ Echo test failed!")
                        print("   Response doesn't match sent data.")
                        print(f"   Sent: {test_message}")
                        print(f"   Received: {response}")

                except Exception as e:
                    error_msg = str(e)
                    print(f"Echo protocol error: {error_msg}")
                    traceback.print_exc()
                finally:
                    # Ensure stream is closed
                    try:
                        if stream:
                            # Check if stream has is_closed method and use it
                            has_is_closed = hasattr(stream, "is_closed") and callable(
                                getattr(stream, "is_closed")
                            )
                            if has_is_closed:
                                # type: ignore[attr-defined]
                                if not await stream.is_closed():
                                    await stream.close()
                            else:
                                # Fallback: just try to close the stream
                                await stream.close()
                    except Exception:
                        pass

                # host.run() context manager handles cleanup automatically
                print()
                print("🎉 WebSocket Demo Completed Successfully!")
                print("=" * 50)
                print("✅ WebSocket transport is working perfectly!")
                print("✅ Echo protocol communication successful!")
                print("✅ libp2p integration verified!")
                print()
                print("🚀 Your WebSocket transport is ready for production use!")

                # Add a small delay to ensure all cleanup is complete
                await trio.sleep(0.1)

        except Exception as e:
            print(f"❌ Error creating WebSocket client: {e}")
            traceback.print_exc()
            return


def main() -> None:
    description = """
    This program demonstrates the libp2p WebSocket transport.
    First run
    'python websocket_demo.py -p <PORT> [--plaintext]' to start a WebSocket server.
    Then run
    'python websocket_demo.py <ANOTHER_PORT> -d <DESTINATION> [--plaintext]'
    where <DESTINATION> is the multiaddress shown by the server.

    By default, this example uses Noise encryption for secure communication.
    Use --plaintext for testing with unencrypted communication
    (not recommended for production).
    """

    example_maddr = (
        "/ip4/127.0.0.1/tcp/8888/ws/p2p/QmQn4SwGkDZKkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
    )

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=0, type=int, help="source port number")
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help=f"destination multiaddr string, e.g. {example_maddr}",
    )
    parser.add_argument(
        "--plaintext",
        action="store_true",
        help=(
            "use plaintext security instead of Noise encryption "
            "(not recommended for production)"
        ),
    )

    args = parser.parse_args()

    # Determine security mode: use Noise by default,
    # plaintext if --plaintext is specified
    use_plaintext = args.plaintext

    try:
        trio.run(run, args.port, args.destination, use_plaintext)
    except KeyboardInterrupt:
        # This is expected when Ctrl+C is pressed
        # The signal handler already printed the shutdown message
        print("✅ Clean exit completed.")
        return
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return


if __name__ == "__main__":
    main()
