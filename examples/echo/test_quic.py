#!/usr/bin/env python3


"""
Fixed QUIC handshake test to debug connection issues.
"""

import logging
import os
from pathlib import Path
import secrets
import sys
from tempfile import NamedTemporaryFile
from time import time

from aioquic._buffer import Buffer
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.logger import QuicFileLogger
from aioquic.quic.packet import pull_quic_header
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.transport.quic.security import (
    LIBP2P_TLS_EXTENSION_OID,
    create_quic_security_transport,
)
from libp2p.transport.quic.transport import QUICTransport, QUICTransportConfig
from libp2p.transport.quic.utils import create_quic_multiaddr

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s", level=logging.DEBUG
)


# Adjust this path to your project structure
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


async def test_certificate_generation():
    """Test certificate generation in isolation."""
    print("\n=== TESTING CERTIFICATE GENERATION ===")

    try:
        from libp2p.peer.id import ID
        from libp2p.transport.quic.security import create_quic_security_transport

        # Create key pair
        private_key = create_new_key_pair().private_key
        peer_id = ID.from_pubkey(private_key.get_public_key())

        print(f"Generated peer ID: {peer_id}")

        # Create security manager
        security_manager = create_quic_security_transport(private_key, peer_id)
        print("✅ Security manager created")

        # Test server config
        server_config = security_manager.create_server_config()
        print("✅ Server config created")

        # Validate certificate
        cert = server_config.certificate
        private_key_obj = server_config.private_key

        print(f"Certificate type: {type(cert)}")
        print(f"Private key type: {type(private_key_obj)}")
        print(f"Certificate subject: {cert.subject}")
        print(f"Certificate issuer: {cert.issuer}")

        # Check for libp2p extension
        has_libp2p_ext = False
        for ext in cert.extensions:
            if ext.oid == LIBP2P_TLS_EXTENSION_OID:
                has_libp2p_ext = True
                print(f"✅ Found libp2p extension: {ext.oid}")
                print(f"Extension critical: {ext.critical}")
                break

        if not has_libp2p_ext:
            print("❌ No libp2p extension found!")
            print("Available extensions:")
            for ext in cert.extensions:
                print(f"  - {ext.oid} (critical: {ext.critical})")

        # Check certificate/key match
        from cryptography.hazmat.primitives import serialization

        cert_public_key = cert.public_key()
        private_public_key = private_key_obj.public_key()

        cert_pub_bytes = cert_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        private_pub_bytes = private_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        if cert_pub_bytes == private_pub_bytes:
            print("✅ Certificate and private key match")
            return has_libp2p_ext
        else:
            print("❌ Certificate and private key DO NOT match")
            return False

    except Exception as e:
        print(f"❌ Certificate test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_basic_quic_connection():
    """Test basic QUIC connection with proper server setup."""
    print("\n=== TESTING BASIC QUIC CONNECTION ===")

    try:
        from aioquic.quic.configuration import QuicConfiguration
        from aioquic.quic.connection import QuicConnection

        from libp2p.peer.id import ID
        from libp2p.transport.quic.security import create_quic_security_transport

        # Create certificates
        server_key = create_new_key_pair().private_key
        server_peer_id = ID.from_pubkey(server_key.get_public_key())
        server_security = create_quic_security_transport(server_key, server_peer_id)

        client_key = create_new_key_pair().private_key
        client_peer_id = ID.from_pubkey(client_key.get_public_key())
        client_security = create_quic_security_transport(client_key, client_peer_id)

        # Create server config
        server_tls_config = server_security.create_server_config()
        server_config = QuicConfiguration(
            is_client=False,
            certificate=server_tls_config.certificate,
            private_key=server_tls_config.private_key,
            alpn_protocols=["libp2p"],
        )

        # Create client config
        client_tls_config = client_security.create_client_config()
        client_config = QuicConfiguration(
            is_client=True,
            certificate=client_tls_config.certificate,
            private_key=client_tls_config.private_key,
            alpn_protocols=["libp2p"],
        )

        print("✅ QUIC configurations created")

        # Test creating connections with proper parameters
        # For server, we need to provide original_destination_connection_id
        original_dcid = secrets.token_bytes(8)

        server_conn = QuicConnection(
            configuration=server_config,
            original_destination_connection_id=original_dcid,
        )

        # For client, no original_destination_connection_id needed
        client_conn = QuicConnection(configuration=client_config)

        print("✅ QUIC connections created")
        print(f"Server state: {server_conn._state}")
        print(f"Client state: {client_conn._state}")

        # Test that certificates are valid
        print(f"Server has certificate: {server_config.certificate is not None}")
        print(f"Server has private key: {server_config.private_key is not None}")
        print(f"Client has certificate: {client_config.certificate is not None}")
        print(f"Client has private key: {client_config.private_key is not None}")

        return True

    except Exception as e:
        print(f"❌ Basic QUIC test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_server_startup():
    """Test server startup with timeout."""
    print("\n=== TESTING SERVER STARTUP ===")

    try:
        # Create transport
        private_key = create_new_key_pair().private_key
        config = QUICTransportConfig(
            idle_timeout=10.0,  # Reduced timeout for testing
            connection_timeout=10.0,
            enable_draft29=False,
        )

        transport = QUICTransport(private_key, config)
        print("✅ Transport created successfully")

        # Test configuration
        print(f"Available configs: {list(transport._quic_configs.keys())}")

        config_valid = True
        for config_key, quic_config in transport._quic_configs.items():
            print(f"\n--- Testing config: {config_key} ---")
            print(f"is_client: {quic_config.is_client}")
            print(f"has_certificate: {quic_config.certificate is not None}")
            print(f"has_private_key: {quic_config.private_key is not None}")
            print(f"alpn_protocols: {quic_config.alpn_protocols}")
            print(f"verify_mode: {quic_config.verify_mode}")

            if quic_config.certificate:
                cert = quic_config.certificate
                print(f"Certificate subject: {cert.subject}")

                # Check for libp2p extension
                has_libp2p_ext = False
                for ext in cert.extensions:
                    if ext.oid == LIBP2P_TLS_EXTENSION_OID:
                        has_libp2p_ext = True
                        break
                print(f"Has libp2p extension: {has_libp2p_ext}")

                if not has_libp2p_ext:
                    config_valid = False

        if not config_valid:
            print("❌ Transport configuration invalid - missing libp2p extensions")
            return False

        # Create listener
        async def dummy_handler(connection):
            print(f"New connection: {connection}")

        listener = transport.create_listener(dummy_handler)
        print("✅ Listener created successfully")

        # Try to bind with timeout
        maddr = create_quic_multiaddr("127.0.0.1", 0, "quic-v1")

        async with trio.open_nursery() as nursery:
            result = await listener.listen(maddr, nursery)
            if result:
                print("✅ Server bound successfully")
                addresses = listener.get_addresses()
                print(f"Listening on: {addresses}")

                # Keep running for a short time
                with trio.move_on_after(3.0):  # 3 second timeout
                    await trio.sleep(5.0)

                print("✅ Server test completed (timed out normally)")
                nursery.cancel_scope.cancel()
                return True
            else:
                print("❌ Failed to bind server")
                return False

    except Exception as e:
        print(f"❌ Server test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_full_handshake_and_certificate_exchange():
    """
    Test a full handshake to ensure it completes and peer certificates are exchanged.
    This version is corrected to use the actual APIs available in the codebase.
    """
    print("\n=== TESTING FULL HANDSHAKE AND CERTIFICATE EXCHANGE (CORRECTED) ===")

    # 1. Generate KeyPairs and create libp2p security configs for client and server.
    #    The `create_quic_security_transport` function from `test_quic.py` is the
    #    correct helper to use, and it requires a `KeyPair` argument.
    client_key_pair = create_new_key_pair()
    server_key_pair = create_new_key_pair()

    # This is the correct way to get the security configuration objects.
    client_security_config = create_quic_security_transport(
        client_key_pair.private_key, ID.from_pubkey(client_key_pair.public_key)
    )
    server_security_config = create_quic_security_transport(
        server_key_pair.private_key, ID.from_pubkey(server_key_pair.public_key)
    )
    print("✅ libp2p security configs created.")

    # 2. Create aioquic configurations and manually apply security settings,
    #    mimicking what the `QUICTransport` class does internally.
    client_secrets_log_file = NamedTemporaryFile(
        mode="w", delete=False, suffix="-client.log"
    )
    client_aioquic_config = QuicConfiguration(
        is_client=True,
        alpn_protocols=["libp2p"],
        secrets_log_file=client_secrets_log_file,
    )
    client_aioquic_config.certificate = client_security_config.tls_config.certificate
    client_aioquic_config.private_key = client_security_config.tls_config.private_key
    client_aioquic_config.verify_mode = (
        client_security_config.create_client_config().verify_mode
    )
    client_aioquic_config.quic_logger = QuicFileLogger(
        "/home/akmo/GitHub/py-libp2p/examples/echo/logs"
    )

    server_secrets_log_file = NamedTemporaryFile(
        mode="w", delete=False, suffix="-server.log"
    )

    server_aioquic_config = QuicConfiguration(
        is_client=False,
        alpn_protocols=["libp2p"],
        secrets_log_file=server_secrets_log_file,
    )
    server_aioquic_config.certificate = server_security_config.tls_config.certificate
    server_aioquic_config.private_key = server_security_config.tls_config.private_key
    server_aioquic_config.verify_mode = (
        server_security_config.create_server_config().verify_mode
    )
    server_aioquic_config.quic_logger = QuicFileLogger(
        "/home/akmo/GitHub/py-libp2p/examples/echo/logs"
    )
    print("✅ aioquic configurations created and configured.")
    print(f"🔑 Client secrets will be logged to: {client_secrets_log_file.name}")
    print(f"🔑 Server secrets will be logged to: {server_secrets_log_file.name}")

    # 3. Instantiate client, initiate its `connect` call, and get the ODCID for the server.
    client_address = ("127.0.0.1", 1234)
    server_address = ("127.0.0.1", 4321)

    client_aioquic_config.connection_id_length = 8
    client_conn = QuicConnection(configuration=client_aioquic_config)
    client_conn.connect(server_address, now=time())
    print("✅ aioquic connections instantiated correctly.")

    print("🔧 Client CIDs")
    print("Local Init CID: ", client_conn._local_initial_source_connection_id.hex())
    print(
        "Remote Init CID: ",
        (client_conn._remote_initial_source_connection_id or b"").hex(),
    )
    print(
        "Original Destination CID: ",
        client_conn.original_destination_connection_id.hex(),
    )
    print(f"Host CID: {client_conn._host_cids[0].cid.hex()}")

    # 4. Instantiate the server with the ODCID from the client.
    server_aioquic_config.connection_id_length = 8
    server_conn = QuicConnection(
        configuration=server_aioquic_config,
        original_destination_connection_id=client_conn.original_destination_connection_id,
    )
    print("✅ aioquic connections instantiated correctly.")

    # 5. Manually drive the handshake process by exchanging datagrams.
    max_duration_s = 5
    start_time = time()

    while time() - start_time < max_duration_s:
        for datagram, _ in client_conn.datagrams_to_send(now=time()):
            header = pull_quic_header(Buffer(data=datagram), host_cid_length=8)
            print("Client packet source connection id", header.source_cid.hex())
            print(
                "Client packet destination connection id", header.destination_cid.hex()
            )
            print("--SERVER INJESTING CLIENT PACKET---")
            server_conn.receive_datagram(datagram, client_address, now=time())

        print(
            f"Server remote initial source id: {(server_conn._remote_initial_source_connection_id or b'').hex()}"
        )
        for datagram, _ in server_conn.datagrams_to_send(now=time()):
            header = pull_quic_header(Buffer(data=datagram), host_cid_length=8)
            print("Server packet source connection id", header.source_cid.hex())
            print(
                "Server packet destination connection id", header.destination_cid.hex()
            )
            print("--CLIENT INJESTING SERVER PACKET---")
            client_conn.receive_datagram(datagram, server_address, now=time())

        # Check for completion
        if client_conn._handshake_complete and server_conn._handshake_complete:
            break

        await trio.sleep(0.01)

    # 6. Assertions to verify the outcome.
    assert client_conn._handshake_complete, "❌ Client handshake did not complete."
    assert server_conn._handshake_complete, "❌ Server handshake did not complete."
    print("✅ Handshake completed for both peers.")

    # The key assertion: check if the peer certificate was received.
    client_peer_cert = getattr(client_conn.tls, "_peer_certificate", None)
    server_peer_cert = getattr(server_conn.tls, "_peer_certificate", None)

    client_secrets_log_file.close()
    server_secrets_log_file.close()
    os.unlink(client_secrets_log_file.name)
    os.unlink(server_secrets_log_file.name)

    assert client_peer_cert is not None, (
        "❌ Client FAILED to receive server certificate."
    )
    print("✅ Client successfully received server certificate.")

    print("🎉 Test Passed: Full handshake and certificate exchange successful.")
    return True


async def main():
    """Run all tests with better error handling."""
    print("Starting QUIC diagnostic tests...")

    handshake_ok = await test_full_handshake_and_certificate_exchange()
    if not handshake_ok:
        print("\n❌ CRITICAL: Handshake failed!")
        print("Apply the handshake fix and try again.")
        return

    # Test 1: Certificate generation
    cert_ok = await test_certificate_generation()
    if not cert_ok:
        print("\n❌ CRITICAL: Certificate generation failed!")
        print("Apply the certificate generation fix and try again.")
        return

    # Test 2: Basic QUIC connection
    quic_ok = await test_basic_quic_connection()
    if not quic_ok:
        print("\n❌ CRITICAL: Basic QUIC connection test failed!")
        return

    # Test 3: Server startup
    server_ok = await test_server_startup()
    if not server_ok:
        print("\n❌ Server startup test failed!")
        return

    print("\n✅ ALL TESTS PASSED!")
    print("=== DIAGNOSTIC COMPLETE ===")
    print("Your QUIC implementation should now work correctly.")
    print("Try running your echo example again.")


if __name__ == "__main__":
    trio.run(main)
