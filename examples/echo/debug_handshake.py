def debug_quic_connection_state(conn, name="Connection"):
    """Enhanced debugging function for QUIC connection state."""
    print(f"\n🔍 === {name} Debug Info ===")

    # Basic connection state
    print(f"State: {getattr(conn, '_state', 'unknown')}")
    print(f"Handshake complete: {getattr(conn, '_handshake_complete', False)}")

    # Connection IDs
    if hasattr(conn, "_host_connection_id"):
        print(
            f"Host CID: {conn._host_connection_id.hex() if conn._host_connection_id else 'None'}"
        )
    if hasattr(conn, "_peer_connection_id"):
        print(
            f"Peer CID: {conn._peer_connection_id.hex() if conn._peer_connection_id else 'None'}"
        )

    # Check for connection ID sequences
    if hasattr(conn, "_local_connection_ids"):
        print(
            f"Local CID sequence: {[cid.cid.hex() for cid in conn._local_connection_ids]}"
        )
    if hasattr(conn, "_remote_connection_ids"):
        print(
            f"Remote CID sequence: {[cid.cid.hex() for cid in conn._remote_connection_ids]}"
        )

    # TLS state
    if hasattr(conn, "tls") and conn.tls:
        tls_state = getattr(conn.tls, "state", "unknown")
        print(f"TLS state: {tls_state}")

        # Check for certificates
        peer_cert = getattr(conn.tls, "_peer_certificate", None)
        print(f"Has peer certificate: {peer_cert is not None}")

    # Transport parameters
    if hasattr(conn, "_remote_transport_parameters"):
        params = conn._remote_transport_parameters
        if params:
            print(f"Remote transport parameters received: {len(params)} params")

    print(f"=== End {name} Debug ===\n")


def debug_firstflight_event(server_conn, name="Server"):
    """Debug connection ID changes specifically around FIRSTFLIGHT event."""
    print(f"\n🎯 === {name} FIRSTFLIGHT Event Debug ===")

    # Connection state
    state = getattr(server_conn, "_state", "unknown")
    print(f"Connection State: {state}")

    # Connection IDs
    peer_cid = getattr(server_conn, "_peer_connection_id", None)
    host_cid = getattr(server_conn, "_host_connection_id", None)
    original_dcid = getattr(server_conn, "original_destination_connection_id", None)

    print(f"Peer CID: {peer_cid.hex() if peer_cid else 'None'}")
    print(f"Host CID: {host_cid.hex() if host_cid else 'None'}")
    print(f"Original DCID: {original_dcid.hex() if original_dcid else 'None'}")

    print(f"=== End {name} FIRSTFLIGHT Debug ===\n")


def create_minimal_quic_test():
    """Simplified test to isolate FIRSTFLIGHT connection ID issues."""
    print("\n=== MINIMAL QUIC FIRSTFLIGHT CONNECTION ID TEST ===")

    from time import time
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.connection import QuicConnection
    from aioquic.buffer import Buffer
    from aioquic.quic.packet import pull_quic_header

    # Minimal configs without certificates first
    client_config = QuicConfiguration(
        is_client=True, alpn_protocols=["libp2p"], connection_id_length=8
    )

    server_config = QuicConfiguration(
        is_client=False, alpn_protocols=["libp2p"], connection_id_length=8
    )

    # Create client and connect
    client_conn = QuicConnection(configuration=client_config)
    server_addr = ("127.0.0.1", 4321)

    print("🔗 Client calling connect()...")
    client_conn.connect(server_addr, now=time())

    # Debug client state after connect
    debug_quic_connection_state(client_conn, "Client After Connect")

    # Get initial client packet
    initial_packets = client_conn.datagrams_to_send(now=time())
    if not initial_packets:
        print("❌ No initial packets from client")
        return False

    initial_packet = initial_packets[0][0]

    # Parse header to get client's source CID (what server should use as peer CID)
    header = pull_quic_header(Buffer(data=initial_packet), host_cid_length=8)
    client_source_cid = header.source_cid
    client_dest_cid = header.destination_cid

    print(f"📦 Initial packet analysis:")
    print(
        f"   Client Source CID: {client_source_cid.hex()} (server should use as peer CID)"
    )
    print(f"   Client Dest CID: {client_dest_cid.hex()}")

    # Create server with proper ODCID
    print(
        f"\n🏗️ Creating server with original_destination_connection_id={client_dest_cid.hex()}..."
    )
    server_conn = QuicConnection(
        configuration=server_config,
        original_destination_connection_id=client_dest_cid,
    )

    # Debug server state after creation (before FIRSTFLIGHT)
    debug_firstflight_event(server_conn, "Server After Creation (Pre-FIRSTFLIGHT)")

    # 🎯 CRITICAL: Process initial packet (this triggers FIRSTFLIGHT event)
    print(f"🚀 Processing initial packet (triggering FIRSTFLIGHT)...")
    client_addr = ("127.0.0.1", 1234)

    # Before receive_datagram
    print(f"📊 BEFORE receive_datagram (FIRSTFLIGHT):")
    print(f"   Server state: {getattr(server_conn, '_state', 'unknown')}")
    print(
        f"   Server peer CID: {server_conn._peer_cid.cid.hex()}"
    )
    print(f"   Expected peer CID after FIRSTFLIGHT: {client_source_cid.hex()}")

    # This call triggers FIRSTFLIGHT: FIRSTFLIGHT -> CONNECTED
    server_conn.receive_datagram(initial_packet, client_addr, now=time())

    # After receive_datagram (FIRSTFLIGHT should have happened)
    print(f"📊 AFTER receive_datagram (Post-FIRSTFLIGHT):")
    print(f"   Server state: {getattr(server_conn, '_state', 'unknown')}")
    print(
        f"   Server peer CID: {server_conn._peer_cid.cid.hex()}"
    )

    # Check if FIRSTFLIGHT set peer CID correctly
    actual_peer_cid = server_conn._peer_cid.cid
    if actual_peer_cid == client_source_cid:
        print("✅ FIRSTFLIGHT correctly set peer CID from client source CID")
        firstflight_success = True
    else:
        print("❌ FIRSTFLIGHT BUG: peer CID not set correctly!")
        print(f"   Expected: {client_source_cid.hex()}")
        print(f"   Actual: {actual_peer_cid.hex() if actual_peer_cid else 'None'}")
        firstflight_success = False

    # Debug both connections after FIRSTFLIGHT
    debug_firstflight_event(server_conn, "Server After FIRSTFLIGHT")
    debug_quic_connection_state(client_conn, "Client After Server Processing")

    # Check server response packets
    print(f"\n📤 Checking server response packets...")
    server_packets = server_conn.datagrams_to_send(now=time())
    if server_packets:
        response_packet = server_packets[0][0]
        response_header = pull_quic_header(
            Buffer(data=response_packet), host_cid_length=8
        )

        print(f"📊 Server response packet:")
        print(f"   Source CID: {response_header.source_cid.hex()}")
        print(f"   Dest CID: {response_header.destination_cid.hex()}")
        print(f"   Expected dest CID: {client_source_cid.hex()}")

        # Final verification
        if response_header.destination_cid == client_source_cid:
            print("✅ Server response uses correct destination CID!")
            return True
        else:
            print(f"❌ Server response uses WRONG destination CID!")
            print(f"   This proves the FIRSTFLIGHT bug - peer CID not set correctly")
            print(f"   Expected: {client_source_cid.hex()}")
            print(f"   Actual: {response_header.destination_cid.hex()}")
            return False
    else:
        print("❌ Server did not generate response packet")
        return False


def create_minimal_quic_test_with_config(client_config, server_config):
    """Run FIRSTFLIGHT test with provided configurations."""
    from time import time
    from aioquic.buffer import Buffer
    from aioquic.quic.connection import QuicConnection
    from aioquic.quic.packet import pull_quic_header

    print("\n=== FIRSTFLIGHT TEST WITH CERTIFICATES ===")

    # Create client and connect
    client_conn = QuicConnection(configuration=client_config)
    server_addr = ("127.0.0.1", 4321)

    print("🔗 Client calling connect() with certificates...")
    client_conn.connect(server_addr, now=time())

    # Get initial packets and extract client source CID
    initial_packets = client_conn.datagrams_to_send(now=time())
    if not initial_packets:
        print("❌ No initial packets from client")
        return False

    # Extract client source CID from initial packet
    initial_packet = initial_packets[0][0]
    header = pull_quic_header(Buffer(data=initial_packet), host_cid_length=8)
    client_source_cid = header.source_cid

    print(f"📦 Client source CID (expected server peer CID): {client_source_cid.hex()}")

    # Create server with client's source CID as original destination
    server_conn = QuicConnection(
        configuration=server_config,
        original_destination_connection_id=client_source_cid,
    )

    # Debug server before FIRSTFLIGHT
    print(f"\n📊 BEFORE FIRSTFLIGHT (server creation):")
    print(f"   Server state: {getattr(server_conn, '_state', 'unknown')}")
    print(
        f"   Server peer CID: {server_conn._peer_cid.cid.hex()}"
    )
    print(
        f"   Server original DCID: {server_conn.original_destination_connection_id.hex()}"
    )

    # Process initial packet (triggers FIRSTFLIGHT)
    client_addr = ("127.0.0.1", 1234)

    print(f"\n🚀 Triggering FIRSTFLIGHT by processing initial packet...")
    for datagram, _ in initial_packets:
        header = pull_quic_header(Buffer(data=datagram))
        print(
            f"   Processing packet: src={header.source_cid.hex()}, dst={header.destination_cid.hex()}"
        )

        # This triggers FIRSTFLIGHT
        server_conn.receive_datagram(datagram, client_addr, now=time())

        # Debug immediately after FIRSTFLIGHT
        print(f"\n📊 AFTER FIRSTFLIGHT:")
        print(f"   Server state: {getattr(server_conn, '_state', 'unknown')}")
        print(
            f"   Server peer CID: {server_conn._peer_cid.cid.hex()}"
        )
        print(f"   Expected peer CID: {header.source_cid.hex()}")

        # Check if FIRSTFLIGHT worked correctly
        actual_peer_cid = getattr(server_conn, "_peer_connection_id", None)
        if actual_peer_cid == header.source_cid:
            print("✅ FIRSTFLIGHT correctly set peer CID")
        else:
            print("❌ FIRSTFLIGHT failed to set peer CID correctly")
            print(f"   This is the root cause of the handshake failure!")

    # Check server response
    server_packets = server_conn.datagrams_to_send(now=time())
    if server_packets:
        response_packet = server_packets[0][0]
        response_header = pull_quic_header(
            Buffer(data=response_packet), host_cid_length=8
        )

        print(f"\n📤 Server response analysis:")
        print(f"   Response dest CID: {response_header.destination_cid.hex()}")
        print(f"   Expected dest CID: {client_source_cid.hex()}")

        if response_header.destination_cid == client_source_cid:
            print("✅ Server response uses correct destination CID!")
            return True
        else:
            print("❌ FIRSTFLIGHT bug confirmed - wrong destination CID in response!")
            print(
                "   This proves aioquic doesn't set peer CID correctly during FIRSTFLIGHT"
            )
            return False

    print("❌ No server response packets")
    return False


async def test_with_certificates():
    """Test with proper certificate setup and FIRSTFLIGHT debugging."""
    print("\n=== CERTIFICATE-BASED FIRSTFLIGHT TEST ===")

    # Import your existing certificate creation functions
    from libp2p.crypto.ed25519 import create_new_key_pair
    from libp2p.peer.id import ID
    from libp2p.transport.quic.security import create_quic_security_transport

    # Create security configs
    client_key_pair = create_new_key_pair()
    server_key_pair = create_new_key_pair()

    client_security_config = create_quic_security_transport(
        client_key_pair.private_key, ID.from_pubkey(client_key_pair.public_key)
    )
    server_security_config = create_quic_security_transport(
        server_key_pair.private_key, ID.from_pubkey(server_key_pair.public_key)
    )

    # Apply the minimal test logic with certificates
    from aioquic.quic.configuration import QuicConfiguration

    client_config = QuicConfiguration(
        is_client=True, alpn_protocols=["libp2p"], connection_id_length=8
    )
    client_config.certificate = client_security_config.tls_config.certificate
    client_config.private_key = client_security_config.tls_config.private_key
    client_config.verify_mode = (
        client_security_config.create_client_config().verify_mode
    )

    server_config = QuicConfiguration(
        is_client=False, alpn_protocols=["libp2p"], connection_id_length=8
    )
    server_config.certificate = server_security_config.tls_config.certificate
    server_config.private_key = server_security_config.tls_config.private_key
    server_config.verify_mode = (
        server_security_config.create_server_config().verify_mode
    )

    # Run the FIRSTFLIGHT test with certificates
    return create_minimal_quic_test_with_config(client_config, server_config)


async def main():
    print("🎯 Testing FIRSTFLIGHT connection ID behavior...")

    # # First test without certificates
    # print("\n" + "=" * 60)
    # print("PHASE 1: Testing FIRSTFLIGHT without certificates")
    # print("=" * 60)
    # minimal_success = create_minimal_quic_test()

    # Then test with certificates
    print("\n" + "=" * 60)
    print("PHASE 2: Testing FIRSTFLIGHT with certificates")
    print("=" * 60)
    cert_success = await test_with_certificates()

    # Summary
    print("\n" + "=" * 60)
    print("FIRSTFLIGHT TEST SUMMARY")
    print("=" * 60)
    # print(f"Minimal test (no certs): {'✅ PASS' if minimal_success else '❌ FAIL'}")
    print(f"Certificate test: {'✅ PASS' if cert_success else '❌ FAIL'}")

    if not cert_success:
        print("\n🔥 FIRSTFLIGHT BUG CONFIRMED:")
        print("   - aioquic fails to set peer CID correctly during FIRSTFLIGHT event")
        print("   - Server uses wrong destination CID in response packets")
        print("   - Client drops responses → handshake fails")
        print("   - Fix: Override _peer_connection_id after receive_datagram()")


if __name__ == "__main__":
    import trio

    trio.run(main)
