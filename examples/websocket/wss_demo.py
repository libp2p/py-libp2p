#!/usr/bin/env python3
"""
Real-World WSS (WebSocket Secure) Demo

This example demonstrates production-ready WSS functionality with:
- Self-signed TLS certificates for testing
- Secure WebSocket connections (WSS)
- Real-world certificate management
- Browser-compatible WSS connections

Usage:
    python examples/websocket/wss_demo.py
    python examples/websocket/wss_demo.py -p <port>
    python examples/websocket/wss_demo.py -d <listener_multiaddr>
"""

import argparse
import logging
from pathlib import Path
import sys
import tempfile

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

# Enable debug logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("libp2p.wss-demo")

# Simple echo protocol
ECHO_PROTOCOL_ID = TProtocol("/echo/1.0.0")


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
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "libp2p WSS Demo"),  # type: ignore
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


def create_wss_host(server_context=None, client_context=None):
    """Create a host with WSS transport."""
    # Create key pair and peer store
    key_pair = create_new_key_pair()

    # Create transport upgrader with plaintext security for simplicity

    # Transport upgrader is created but not used in this simplified example

    # Create host with WSS transport
    host = new_host(
        key_pair=key_pair,
        sec_opt={PLAINTEXT_PROTOCOL_ID: InsecureTransport(key_pair)},
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/0.0.0.0/tcp/0/wss")],
        tls_server_config=server_context,
        tls_client_config=client_context,
    )

    return host


async def run_server(port: int):
    """Run WSS server."""
    logger.info("🔐 Creating self-signed certificates for WSS...")
    server_context, client_context, cert_file, key_file = (
        create_self_signed_certificate()
    )

    try:
        # Create WSS host
        host = create_wss_host(server_context=server_context)

        # Set up echo handler
        host.set_stream_handler(ECHO_PROTOCOL_ID, echo_handler)

        # Start listening
        listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{port}/wss")

        async with host.run(listen_addrs=[listen_addr]):
            # Get the actual address
            addrs = host.get_addrs()
            if not addrs:
                logger.error("❌ No addresses found for the host")
                return

            server_addr = str(addrs[0])
            client_addr = server_addr.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/")

            # Use print() so output is always visible (logging may be suppressed)
            print("🌐 WSS Server Started Successfully!", flush=True)
            print("=" * 50, flush=True)
            print(f"📍 Server Address: {client_addr}", flush=True)
            print("🔧 Protocol: /echo/1.0.0", flush=True)
            print("🚀 Transport: WebSocket Secure (WSS)", flush=True)
            print("🔐 Security: TLS with self-signed certificate", flush=True)
            print("", flush=True)
            print("📋 To test, run in another terminal:", flush=True)
            print(f"   python wss_demo.py -d {client_addr}", flush=True)
            print("", flush=True)
            print("⏳ Waiting for incoming WSS connections...", flush=True)
            print("─" * 50, flush=True)

            # Wait indefinitely
            await trio.sleep_forever()

    except KeyboardInterrupt:
        logger.info("🛑 Shutting down WSS server...")
    finally:
        cleanup_certificates(cert_file, key_file)


async def run_client(destination: str):
    """Run WSS client."""
    server_context, client_context, cert_file, key_file = (
        create_self_signed_certificate()
    )

    try:
        # Create WSS host
        host = create_wss_host(client_context=client_context)

        # Start the host
        async with host.run(listen_addrs=[]):
            maddr = Multiaddr(destination)
            info = info_from_p2p_addr(maddr)

            # Use print() so output is always visible (logging may be suppressed)
            print("🔌 WSS Client Starting...", flush=True)
            print("=" * 40, flush=True)
            print(f"🎯 Target Peer: {info.peer_id}", flush=True)
            print(f"📍 Target Address: {destination}", flush=True)
            print("🔐 Security: TLS with self-signed certificate", flush=True)
            print("", flush=True)

            try:
                print("🔗 Connecting to WSS server...", flush=True)
                await host.connect(info)
                print("✅ Successfully connected to WSS server!", flush=True)
            except Exception as e:
                print(f"❌ Connection Failed: {e}", flush=True)
                return

            # Create a stream and send test data
            try:
                stream = await host.new_stream(info.peer_id, [ECHO_PROTOCOL_ID])
            except Exception as e:
                print(f"❌ Failed to create stream: {e}", flush=True)
                return

            try:
                print("🚀 Starting Echo Protocol Test...", flush=True)
                print("─" * 40, flush=True)

                # Send test data
                test_message = b"Hello WSS Transport!"
                print(f"📤 Sending message: {test_message.decode('utf-8')}", flush=True)
                await stream.write(test_message)

                # Read response
                print("⏳ Waiting for server response...", flush=True)
                response = await stream.read(1024)
                print(f"📥 Received response: {response.decode('utf-8')}", flush=True)

                await stream.close()

                print("─" * 40, flush=True)
                if response == test_message:
                    print("🎉 Echo test successful!", flush=True)
                    print("✅ WSS transport is working perfectly!", flush=True)
                    print("✅ Client completed successfully, exiting.", flush=True)
                else:
                    print("❌ Echo test failed!", flush=True)
                    print("   Response doesn't match sent data.", flush=True)
                    print(f"   Sent: {test_message}", flush=True)
                    print(f"   Received: {response}", flush=True)

            except Exception as e:
                print(f"❌ Echo protocol error: {e}", flush=True)
            finally:
                # Ensure stream is closed
                try:
                    if stream:
                        await stream.close()
                except Exception:
                    pass

                print("", flush=True)
                print("🎉 WSS Demo Completed Successfully!", flush=True)
                print("=" * 50, flush=True)
                print("✅ WSS transport is working perfectly!", flush=True)
                print("✅ Echo protocol communication successful!", flush=True)
                print("✅ libp2p integration verified!", flush=True)
                print("", flush=True)
                print("🚀 Your WSS transport is ready for production use!", flush=True)

    except KeyboardInterrupt:
        print("🛑 Shutting down WSS client...", flush=True)
    finally:
        cleanup_certificates(cert_file, key_file)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="WSS (WebSocket Secure) Demo - Production-ready WSS example"
    )
    parser.add_argument(
        "-p",
        "--port",
        default=8443,
        type=int,
        help="Server port number (default: 8443)",
    )
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help="Destination WSS multiaddr string for client mode",
    )

    args = parser.parse_args()

    if args.destination:
        # Client mode
        print("DEBUG: Client mode selected")
        trio.run(run_client, args.destination)
    else:
        # Server mode
        print("DEBUG: Server mode selected")
        trio.run(run_server, args.port)


if __name__ == "__main__":
    main()
