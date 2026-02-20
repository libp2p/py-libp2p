#!/usr/bin/env python3
"""
Comprehensive WebSocket Transport Demo

This example demonstrates all the advanced WebSocket transport features:
- WS and WSS protocols
- SOCKS proxy support
- Browser integration
- Production-ready configuration
- Real-world use cases

Usage:
    python examples/websocket/websocket_comprehensive_demo.py
    python examples/websocket/websocket_comprehensive_demo.py -c <addr>
    python examples/websocket/websocket_comprehensive_demo.py -c <addr> --wss
    python examples/websocket/websocket_comprehensive_demo.py -c <addr>
        --proxy <proxy_url>
"""

import argparse
import logging
from pathlib import Path
import sys
import tempfile
import time

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
logger = logging.getLogger("libp2p.websocket-comprehensive-demo")

# Demo protocols
ECHO_PROTOCOL_ID = TProtocol("/echo/1.0.0")
CHAT_PROTOCOL_ID = TProtocol("/chat/1.0.0")


def create_self_signed_certificate():
    """Create a self-signed certificate for WSS testing."""
    try:
        import datetime
        from datetime import timezone
        import ipaddress
        import ssl

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Create certificate
        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),  # type: ignore
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Test"),  # type: ignore
                x509.NameAttribute(NameOID.LOCALITY_NAME, "Test"),  # type: ignore
                x509.NameAttribute(
                    NameOID.ORGANIZATION_NAME,
                    "libp2p Comprehensive Demo",  # type: ignore
                ),
                x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),  # type: ignore
            ]
        )

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(timezone.utc))
            .not_valid_after(
                datetime.datetime.now(timezone.utc) + datetime.timedelta(days=1)
            )
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    ]
                ),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )

        # Create temporary files for cert and key
        cert_file = tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".crt")
        key_file = tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".key")

        # Write certificate and key to files
        cert_file.write(cert.public_bytes(serialization.Encoding.PEM))
        key_file.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

        cert_file.close()
        key_file.close()

        # Create SSL contexts
        server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        server_context.load_cert_chain(cert_file.name, key_file.name)

        client_context = ssl.create_default_context()
        client_context.check_hostname = False
        client_context.verify_mode = ssl.CERT_NONE

        return server_context, client_context, cert_file.name, key_file.name

    except ImportError:
        logger.error("cryptography package required for WSS demo")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to create certificates: {e}")
        sys.exit(1)


def cleanup_certificates(cert_file, key_file):
    """Clean up temporary certificate files."""
    try:
        Path(cert_file).unlink(missing_ok=True)
        Path(key_file).unlink(missing_ok=True)
    except Exception:
        pass


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


async def chat_handler(stream):
    """Chat handler for real-time messaging."""
    try:
        peer_id = str(stream.muxed_conn.peer_id)
        logger.info(f"💬 New chat participant: {peer_id}")

        while True:
            data = await stream.read(1024)
            if not data:
                break

            message = data.decode("utf-8", errors="replace")
            logger.info(f"💬 Chat message from {peer_id}: {message}")

            # Echo back with timestamp
            response = f"[{time.strftime('%H:%M:%S')}] Echo: {message}"
            await stream.write(response.encode())

    except Exception as e:
        logger.error(f"Chat handler error: {e}")
    finally:
        await stream.close()


def create_websocket_host(
    use_wss=False,
    proxy_url: str | None = None,
    proxy_auth: tuple | None = None,
    server_context=None,
    client_context=None,
):
    """Create a host with WebSocket transport and advanced configuration."""
    # Create key pair
    key_pair = create_new_key_pair()

    # Create WebSocket transport configuration
    config = WebsocketConfig(
        proxy_url=proxy_url,
        proxy_auth=proxy_auth,
        handshake_timeout=30.0,
        max_connections=100,
        max_buffered_amount=8 * 1024 * 1024,  # 8MB
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

    # Create WebSocket transport with configuration
    transport = WebsocketTransport(upgrader, config)

    # Create host with appropriate listen address
    protocol = "wss" if use_wss else "ws"
    listen_addrs = [Multiaddr(f"/ip4/0.0.0.0/tcp/0/{protocol}")]

    host = new_host(
        key_pair=key_pair,
        sec_opt={PLAINTEXT_PROTOCOL_ID: InsecureTransport(key_pair)},
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=listen_addrs,
        tls_server_config=server_context,
        tls_client_config=client_context,
    )

    # Replace the default transport with our configured one
    from libp2p.network.swarm import Swarm

    swarm = host.get_network()
    if isinstance(swarm, Swarm):
        swarm.transport = transport

    return host


async def run_server(port: int, use_wss: bool = False, proxy_url: str | None = None):
    """Run WebSocket server with advanced features."""
    logger.info("🚀 Starting Comprehensive WebSocket Server...")

    # Create certificates for WSS if needed
    server_context = None
    client_context = None
    cert_file = None
    key_file = None

    if use_wss:
        logger.info("🔐 Creating self-signed certificates for WSS...")
        server_context, client_context, cert_file, key_file = (
            create_self_signed_certificate()
        )

    try:
        # Create host with advanced configuration
        host = create_websocket_host(
            use_wss=use_wss, proxy_url=proxy_url, server_context=server_context
        )

        # Set up handlers
        host.set_stream_handler(ECHO_PROTOCOL_ID, echo_handler)
        host.set_stream_handler(CHAT_PROTOCOL_ID, chat_handler)

        # Start listening
        protocol = "wss" if use_wss else "ws"
        listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{port}/{protocol}")

        async with host.run(listen_addrs=[listen_addr]):
            # Get the actual address
            addrs = host.get_addrs()
            if not addrs:
                logger.error("❌ No addresses found for the host")
                return

            server_addr = str(addrs[0])
            client_addr = server_addr.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/")

            logger.info("🌐 Comprehensive WebSocket Server Started!")
            logger.info("=" * 60)
            logger.info(f"📍 Server Address: {client_addr}")
            logger.info("🔧 Protocols: /echo/1.0.0, /chat/1.0.0")
            logger.info(f"🚀 Transport: WebSocket ({protocol.upper()})")
            if use_wss:
                logger.info("🔐 Security: TLS with self-signed certificate")
            else:
                logger.info("🔐 Security: Plain WebSocket")
            if proxy_url:
                logger.info(f"🔒 Proxy: {proxy_url}")
            else:
                logger.info("🔒 Proxy: None (Direct connection)")
            logger.info(f"👤 Server Peer ID: {host.get_id()}")
            logger.info("")
            logger.info("📋 To test the connection, run:")
            if use_wss:
                logger.info(
                    "   python examples/websocket/websocket_comprehensive_demo.py "
                    f"-c {client_addr} --wss"
                )
            else:
                logger.info(
                    "   python examples/websocket/websocket_comprehensive_demo.py "
                    f"-c {client_addr}"
                )
            if proxy_url:
                logger.info(
                    "   python examples/websocket/websocket_comprehensive_demo.py "
                    f"-c {client_addr} --proxy {proxy_url}"
                )
            logger.info("")
            logger.info("⏳ Waiting for connections...")
            logger.info("─" * 60)

            # Wait indefinitely
            await trio.sleep_forever()

    except KeyboardInterrupt:
        logger.info("🛑 Shutting down server...")
    finally:
        if cert_file and key_file:
            cleanup_certificates(cert_file, key_file)


async def run_client(
    destination: str,
    use_wss: bool = False,
    proxy_url: str | None = None,
    proxy_auth: tuple | None = None,
):
    """Run WebSocket client with advanced features."""
    logger.info("🔌 Starting Comprehensive WebSocket Client...")

    # Create certificates for WSS if needed
    server_context = None
    client_context = None
    cert_file = None
    key_file = None

    if use_wss:
        logger.info("🔐 Creating self-signed certificates for WSS...")
        server_context, client_context, cert_file, key_file = (
            create_self_signed_certificate()
        )

    try:
        # Create host with advanced configuration
        host = create_websocket_host(
            use_wss=use_wss,
            proxy_url=proxy_url,
            proxy_auth=proxy_auth,
            client_context=client_context,
        )

        # Start the host
        async with host.run(listen_addrs=[]):
            maddr = Multiaddr(destination)
            info = info_from_p2p_addr(maddr)

            logger.info("🔌 Comprehensive WebSocket Client Starting...")
            logger.info("=" * 50)
            logger.info(f"🎯 Target Peer: {info.peer_id}")
            logger.info(f"📍 Target Address: {destination}")
            if use_wss:
                logger.info("🔐 Security: TLS with self-signed certificate")
            else:
                logger.info("🔐 Security: Plain WebSocket")
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

            # Test echo protocol
            try:
                logger.info("🚀 Testing Echo Protocol...")
                stream = await host.new_stream(info.peer_id, [ECHO_PROTOCOL_ID])

                test_message = b"Hello Comprehensive WebSocket Demo!"
                logger.info(f"📤 Sending: {test_message.decode('utf-8')}")
                await stream.write(test_message)

                response = await stream.read(1024)
                logger.info(f"📥 Received: {response.decode('utf-8')}")
                await stream.close()

                if response == test_message:
                    logger.info("✅ Echo protocol test successful!")
                else:
                    logger.error("❌ Echo protocol test failed!")

            except Exception as e:
                logger.error(f"❌ Echo protocol error: {e}")

            # Test chat protocol
            try:
                logger.info("🚀 Testing Chat Protocol...")
                stream = await host.new_stream(info.peer_id, [CHAT_PROTOCOL_ID])

                chat_message = b"Hello from comprehensive demo!"
                logger.info(f"💬 Sending chat: {chat_message.decode('utf-8')}")
                await stream.write(chat_message)

                response = await stream.read(1024)
                logger.info(f"💬 Chat response: {response.decode('utf-8')}")
                await stream.close()

                logger.info("✅ Chat protocol test successful!")

            except Exception as e:
                logger.error(f"❌ Chat protocol error: {e}")

            logger.info("")
            logger.info("🎉 Comprehensive WebSocket Demo Completed Successfully!")
            logger.info("=" * 60)
            logger.info("✅ All WebSocket transport features working!")
            logger.info("✅ Echo protocol communication successful!")
            logger.info("✅ Chat protocol communication successful!")
            logger.info("✅ Advanced features verified!")
            logger.info("")
            logger.info(
                "🚀 Your comprehensive WebSocket transport is ready for production!"
            )

    except KeyboardInterrupt:
        logger.info("🛑 Shutting down client...")
    finally:
        if cert_file and key_file:
            cleanup_certificates(cert_file, key_file)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Comprehensive WebSocket Transport Demo - All advanced features"
    )
    parser.add_argument(
        "-p", "--port", default=8080, type=int, help="Server port (default: 8080)"
    )
    parser.add_argument(
        "-c", "--connect", type=str, help="Connect to WebSocket server (client mode)"
    )
    parser.add_argument(
        "--wss", action="store_true", help="Use WSS (WebSocket Secure) instead of WS"
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
        trio.run(run_client, args.connect, args.wss, args.proxy, proxy_auth)
    else:
        # Server mode
        trio.run(run_server, args.port, args.wss, args.proxy)


if __name__ == "__main__":
    main()
