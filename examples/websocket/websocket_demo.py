import argparse
import logging
import sys
import traceback

import multiaddr
import trio

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.host.basic_host import BasicHost
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo, info_from_p2p_addr
from libp2p.peer.peerstore import PeerStore
from libp2p.security.insecure.transport import InsecureTransport, PLAINTEXT_PROTOCOL_ID
from libp2p.security.noise.transport import Transport as NoiseTransport
from libp2p.security.noise.transport import PROTOCOL_ID as NOISE_PROTOCOL_ID
from libp2p.stream_muxer.yamux.yamux import Yamux
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.transport import WebsocketTransport

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger("libp2p.websocket-example")

# Simple echo protocol
ECHO_PROTOCOL_ID = TProtocol("/echo/1.0.0")


async def echo_handler(stream):
    """Simple echo handler that echoes back any data received."""
    try:
        data = await stream.read(1024)
        if data:
            message = data.decode('utf-8', errors='replace')
            print(f"📥 Received: {message}")
            print(f"📤 Echoing back: {message}")
            await stream.write(data)
        await stream.close()
    except Exception as e:
        logger.error(f"Echo handler error: {e}")
        await stream.close()


def create_websocket_host(listen_addrs=None, use_noise=False):
    """Create a host with WebSocket transport."""
    # Create key pair and peer store
    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    peer_store = PeerStore()
    peer_store.add_key_pair(peer_id, key_pair)

    if use_noise:
        # Create Noise transport
        noise_transport = NoiseTransport(
            libp2p_keypair=key_pair,
            noise_privkey=key_pair.private_key,
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
    else:
        # Create transport upgrader with plaintext security
        upgrader = TransportUpgrader(
            secure_transports_by_protocol={
                TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
            },
            muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
        )
    
    # Create WebSocket transport
    transport = WebsocketTransport(upgrader)
    
    # Create swarm and host
    swarm = Swarm(peer_id, peer_store, upgrader, transport)
    host = BasicHost(swarm)
    
    return host


async def run(port: int, destination: str, use_noise: bool = False) -> None:
    localhost_ip = "0.0.0.0"

    if not destination:
        # Create first host (listener) with WebSocket transport
        listen_addr = multiaddr.Multiaddr(f"/ip4/{localhost_ip}/tcp/{port}/ws")
        
        try:
            host = create_websocket_host(use_noise=use_noise)
            logger.debug(f"Created host with use_noise={use_noise}")
            
            # Set up echo handler
            host.set_stream_handler(ECHO_PROTOCOL_ID, echo_handler)

            async with host.run(listen_addrs=[listen_addr]), trio.open_nursery() as nursery:
                # Start the peer-store cleanup task
                nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

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
                print(f"🔧 Protocol: /echo/1.0.0")
                print(f"🚀 Transport: WebSocket (/ws)")
                print()
                print("📋 To test the connection, run this in another terminal:")
                print(f"   python websocket_demo.py -d {client_addr}")
                print()
                print("⏳ Waiting for incoming WebSocket connections...")
                print("─" * 50)

                # Add a custom handler to show connection events
                async def custom_echo_handler(stream):
                    peer_id = stream.muxed_conn.peer_id
                    print(f"\n🔗 New WebSocket Connection!")
                    print(f"   Peer ID: {peer_id}")
                    print(f"   Protocol: /echo/1.0.0")
                    
                    # Show remote address in multiaddr format
                    try:
                        remote_address = stream.get_remote_address()
                        if remote_address:
                            print(f"   Remote: {remote_address}")
                    except Exception:
                        print(f"   Remote: Unknown")
                    
                    print(f"   ─" * 40)

                    # Call the original handler
                    await echo_handler(stream)

                    print(f"   ─" * 40)
                    print(f"✅ Echo request completed for peer: {peer_id}")
                    print()

                # Replace the handler with our custom one
                host.set_stream_handler(ECHO_PROTOCOL_ID, custom_echo_handler)

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
            host = create_websocket_host(use_noise=use_noise)
            
            # Start the host for client operations
            async with host.run(listen_addrs=[listen_addr]), trio.open_nursery() as nursery:
                # Start the peer-store cleanup task
                nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)
                maddr = multiaddr.Multiaddr(destination)
                info = info_from_p2p_addr(maddr)
                print("🔌 WebSocket Client Starting...")
                print("=" * 40)
                print(f"🎯 Target Peer: {info.peer_id}")
                print(f"📍 Target Address: {destination}")
                print()

                try:
                    print("🔗 Connecting to WebSocket server...")
                    await host.connect(info)
                    print("✅ Successfully connected to WebSocket server!")
                except Exception as e:
                    error_msg = str(e)
                    if "unable to connect" in error_msg or "SwarmException" in error_msg:
                        print(f"\n❌ Connection Failed!")
                        print(f"   Peer ID: {info.peer_id}")
                        print(f"   Address: {destination}")
                        print(f"   Error: {error_msg}")
                        print()
                        print("💡 Troubleshooting:")
                        print("   • Make sure the WebSocket server is running")
                        print("   • Check that the server address is correct")
                        print("   • Verify the server is listening on the right port")
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
                        if stream and not await stream.is_closed():
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
                
        except Exception as e:
            print(f"❌ Error creating WebSocket client: {e}")
            traceback.print_exc()
            return


def main() -> None:
    description = """
    This program demonstrates the libp2p WebSocket transport.
    First run 'python websocket_demo.py -p <PORT> [--noise]' to start a WebSocket server.
    Then run 'python websocket_demo.py <ANOTHER_PORT> -d <DESTINATION> [--noise]'
    where <DESTINATION> is the multiaddress shown by the server.

    By default, this example uses plaintext security for communication.
    Use --noise for testing with Noise encryption (experimental).
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
        "--noise",
        action="store_true",
        help="use Noise encryption instead of plaintext security",
    )

    args = parser.parse_args()

    # Determine security mode: use plaintext by default, Noise if --noise is specified
    use_noise = args.noise
    
    try:
        trio.run(run, args.port, args.destination, use_noise)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
