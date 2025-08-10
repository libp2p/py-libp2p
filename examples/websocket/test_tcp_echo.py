#!/usr/bin/env python3
"""
Simple TCP echo demo to verify basic libp2p functionality.
"""

import argparse
import logging
import traceback

import multiaddr
import trio

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.host.basic_host import BasicHost
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.peer.peerstore import PeerStore
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
from libp2p.stream_muxer.yamux.yamux import Yamux
from libp2p.transport.tcp.tcp import TCP
from libp2p.transport.upgrader import TransportUpgrader

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger("libp2p.tcp-example")

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


def create_tcp_host():
    """Create a host with TCP transport."""
    # Create key pair and peer store
    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    peer_store = PeerStore()
    peer_store.add_key_pair(peer_id, key_pair)

    # Create transport upgrader with plaintext security
    upgrader = TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
    )

    # Create TCP transport
    transport = TCP()

    # Create swarm and host
    swarm = Swarm(peer_id, peer_store, upgrader, transport)
    host = BasicHost(swarm)

    return host


async def run(port: int, destination: str) -> None:
    localhost_ip = "0.0.0.0"

    if not destination:
        # Create first host (listener) with TCP transport
        listen_addr = multiaddr.Multiaddr(f"/ip4/{localhost_ip}/tcp/{port}")

        try:
            host = create_tcp_host()
            logger.debug("Created TCP host")

            # Set up echo handler
            host.set_stream_handler(ECHO_PROTOCOL_ID, echo_handler)

            async with (
                host.run(listen_addrs=[listen_addr]),
                trio.open_nursery() as (nursery),
            ):
                # Start the peer-store cleanup task
                nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

                # Get the actual address and replace 0.0.0.0 with 127.0.0.1 for client
                # connections
                addrs = host.get_addrs()
                logger.debug(f"Host addresses: {addrs}")
                if not addrs:
                    print("❌ Error: No addresses found for the host")
                    return

                server_addr = str(addrs[0])
                client_addr = server_addr.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/")

                print("🌐 TCP Server Started Successfully!")
                print("=" * 50)
                print(f"📍 Server Address: {client_addr}")
                print("🔧 Protocol: /echo/1.0.0")
                print("🚀 Transport: TCP")
                print()
                print("📋 To test the connection, run this in another terminal:")
                print(f"   python test_tcp_echo.py -d {client_addr}")
                print()
                print("⏳ Waiting for incoming TCP connections...")
                print("─" * 50)

                await trio.sleep_forever()

        except Exception as e:
            print(f"❌ Error creating TCP server: {e}")
            traceback.print_exc()
            return

    else:
        # Create second host (dialer) with TCP transport
        listen_addr = multiaddr.Multiaddr(f"/ip4/{localhost_ip}/tcp/{port}")

        try:
            # Create a single host for client operations
            host = create_tcp_host()

            # Start the host for client operations
            async with (
                host.run(listen_addrs=[listen_addr]),
                trio.open_nursery() as (nursery),
            ):
                # Start the peer-store cleanup task
                nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)
                maddr = multiaddr.Multiaddr(destination)
                info = info_from_p2p_addr(maddr)
                print("🔌 TCP Client Starting...")
                print("=" * 40)
                print(f"🎯 Target Peer: {info.peer_id}")
                print(f"📍 Target Address: {destination}")
                print()

                try:
                    print("🔗 Connecting to TCP server...")
                    await host.connect(info)
                    print("✅ Successfully connected to TCP server!")
                except Exception as e:
                    error_msg = str(e)
                    print("\n❌ Connection Failed!")
                    print(f"   Peer ID: {info.peer_id}")
                    print(f"   Address: {destination}")
                    print(f"   Error: {error_msg}")
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
                    test_message = b"Hello TCP Transport!"
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
                        print("✅ TCP transport is working perfectly!")
                    else:
                        print("❌ Echo test failed!")

                except Exception as e:
                    print(f"Echo protocol error: {e}")
                    traceback.print_exc()

                print("✅ TCP demo completed successfully!")

        except Exception as e:
            print(f"❌ Error creating TCP client: {e}")
            traceback.print_exc()
            return


def main() -> None:
    description = "Simple TCP echo demo for libp2p"
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=0, type=int, help="source port number")
    parser.add_argument(
        "-d", "--destination", type=str, help="destination multiaddr string"
    )

    args = parser.parse_args()

    try:
        trio.run(run, args.port, args.destination)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
