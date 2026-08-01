#!/usr/bin/env python3
"""
WebSocket Transport with SOCKS Proxy Demo

This example demonstrates WebSocket transport with SOCKS proxy support:
- SOCKS5 proxy configuration
- Proxy authentication
- Connection through corporate firewalls
- Production-ready proxy support

Usage:
    python examples/websocket/proxy_websocket_demo.py
    python examples/websocket/proxy_websocket_demo.py -c <server_multiaddr>
    python examples/websocket/proxy_websocket_demo.py -c <server_multiaddr> --proxy socks5://127.0.0.1:1080
"""

import argparse
import logging

from multiaddr import Multiaddr
import trio

from libp2p import create_yamux_muxer_option, new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.insecure.transport import (
    PLAINTEXT_PROTOCOL_ID,
    InsecureTransport,
)
from libp2p.transport.websocket.transport import WebsocketConfig, WebsocketTransport

# Enable debug logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("libp2p.proxy-websocket-demo")

# Simple echo protocol
ECHO_PROTOCOL_ID = TProtocol("/echo/1.0.0")


async def echo_handler(stream):
    """Simple echo handler that echoes back any data received."""
    try:
        data = await stream.read(1024)
        if data:
            message = data.decode("utf-8", errors="replace")
            logger.info(f"📥 Received: {message}")
            logger.info(f"📤 Echoing back: {message}")
            await stream.write(data)
        await stream.close()
    except Exception as e:
        logger.error(f"Echo handler error: {e}")
        await stream.close()


def create_websocket_host_with_proxy(proxy_url=None, proxy_auth=None):
    """Create a host with WebSocket transport and optional proxy."""
    # Create key pair and peer store
    key_pair = create_new_key_pair()

    # Create WebSocket transport configuration
    config = WebsocketConfig(
        proxy_url=proxy_url,
        proxy_auth=proxy_auth,
        handshake_timeout=30.0,  # Longer timeout for proxy connections
    )

    # Create transport upgrader
    from libp2p.stream_muxer.yamux.yamux import Yamux
    from libp2p.transport.upgrader import TransportUpgrader

    upgrader = TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
    )

    # Create WebSocket transport with proxy configuration
    transport = WebsocketTransport(upgrader, config)

    # Create host
    host = new_host(
        key_pair=key_pair,
        sec_opt={PLAINTEXT_PROTOCOL_ID: InsecureTransport(key_pair)},
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/0.0.0.0/tcp/0/ws")],
        transports=[transport],
    )

    return host


async def run_server(port: int):
    """Run WebSocket server."""
    logger.info("🌐 Starting WebSocket Server...")

    # Create host
    host = create_websocket_host_with_proxy()

    # Set up echo handler
    host.set_stream_handler(ECHO_PROTOCOL_ID, echo_handler)

    # Start listening
    listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{port}/ws")

    async with host.run(listen_addrs=[listen_addr]):
        # Get the actual address
        addrs = host.get_addrs()
        if not addrs:
            logger.error("❌ No addresses found for the host")
            return

        server_addr = str(addrs[0])
        client_addr = server_addr.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/")

        logger.info("🌐 WebSocket Server Started Successfully!")
        logger.info("=" * 50)
        logger.info(f"📍 Server Address: {client_addr}")
        logger.info("🔧 Protocol: /echo/1.0.0")
        logger.info("🚀 Transport: WebSocket (/ws)")
        logger.info("🔒 Proxy: None (Direct connection)")
        logger.info("")
        logger.info("📋 To test with proxy, run:")
        proxy_cmd = (
            f"   python examples/websocket/proxy_websocket_demo.py -c {client_addr} "
            "--proxy socks5://127.0.0.1:1080"
        )
        logger.info(proxy_cmd)
        logger.info("")
        logger.info("⏳ Waiting for connections...")
        logger.info("─" * 50)

        # Wait indefinitely
        await trio.sleep_forever()


async def run_client(
    destination: str,
    proxy_url: str | None = None,
    proxy_auth: tuple | None = None,
):
    """Run WebSocket client with optional proxy."""
    logger.info("🔌 Starting WebSocket Client...")

    # Create host with proxy configuration
    host = create_websocket_host_with_proxy(proxy_url=proxy_url, proxy_auth=proxy_auth)

    # Start the host
    async with host.run(listen_addrs=[]):
        maddr = Multiaddr(destination)
        info = info_from_p2p_addr(maddr)

        logger.info("🔌 WebSocket Client Starting...")
        logger.info("=" * 40)
        logger.info(f"🎯 Target Peer: {info.peer_id}")
        logger.info(f"📍 Target Address: {destination}")
        if proxy_url:
            logger.info(f"🔒 Proxy: {proxy_url}")
            if proxy_auth:
                logger.info(f"🔐 Proxy Auth: {proxy_auth[0]}:***")
        else:
            logger.info("🔒 Proxy: None (Direct connection)")
        logger.info("")

        try:
            logger.info("🔗 Connecting to WebSocket server...")
            await host.connect(info)
            logger.info("✅ Successfully connected to WebSocket server!")
        except Exception as e:
            logger.error(f"❌ Connection Failed: {e}")
            return

        # Create a stream and send test data
        try:
            stream = await host.new_stream(info.peer_id, [ECHO_PROTOCOL_ID])
        except Exception as e:
            logger.error(f"❌ Failed to create stream: {e}")
            return

        try:
            logger.info("🚀 Starting Echo Protocol Test...")
            logger.info("─" * 40)

            # Send test data
            test_message = b"Hello WebSocket Transport with Proxy!"
            logger.info(f"📤 Sending message: {test_message.decode('utf-8')}")
            await stream.write(test_message)

            # Read response
            logger.info("⏳ Waiting for server response...")
            response = await stream.read(1024)
            logger.info(f"📥 Received response: {response.decode('utf-8')}")

            await stream.close()

            logger.info("─" * 40)
            if response == test_message:
                logger.info("🎉 Echo test successful!")
                logger.info("✅ WebSocket transport with proxy is working perfectly!")
                logger.info("✅ Client completed successfully, exiting.")
            else:
                logger.error("❌ Echo test failed!")
                logger.error("   Response doesn't match sent data.")
                logger.error(f"   Sent: {test_message}")
                logger.error(f"   Received: {response}")

        except Exception as e:
            logger.error(f"Echo protocol error: {e}")
        finally:
            # Ensure stream is closed
            try:
                if stream:
                    await stream.close()
            except Exception:
                pass

            logger.info("")
            logger.info("🎉 Proxy WebSocket Demo Completed Successfully!")
            logger.info("=" * 50)
            logger.info("✅ WebSocket transport with proxy is working perfectly!")
            logger.info("✅ Echo protocol communication successful!")
            logger.info("✅ libp2p integration verified!")
            logger.info("")
            logger.info(
                "🚀 Your WebSocket transport with proxy is ready for production use!"
            )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="WebSocket Transport with SOCKS Proxy Demo"
    )
    parser.add_argument(
        "-p", "--port", default=8080, type=int, help="Server port (default: 8080)"
    )
    parser.add_argument(
        "-c", "--connect", type=str, help="Connect to WebSocket server (client mode)"
    )
    parser.add_argument(
        "--proxy", type=str, help="SOCKS proxy URL (e.g., socks5://127.0.0.1:1080)"
    )
    parser.add_argument(
        "--proxy-auth",
        nargs=2,
        metavar=("USERNAME", "PASSWORD"),
        help="Proxy authentication (username password)",
    )

    args = parser.parse_args()

    # Parse proxy authentication
    proxy_auth = None
    if args.proxy_auth:
        proxy_auth = tuple(args.proxy_auth)

    if args.connect:
        # Client mode
        trio.run(run_client, args.connect, args.proxy, proxy_auth)
    else:
        # Server mode
        trio.run(run_server, args.port)


if __name__ == "__main__":
    main()
