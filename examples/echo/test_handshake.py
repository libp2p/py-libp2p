from aioquic._buffer import Buffer
from aioquic.quic.packet import pull_quic_header
from aioquic.quic.connection import QuicConnection
from aioquic.quic.configuration import QuicConfiguration
from tempfile import NamedTemporaryFile
from libp2p.peer.id import ID
from libp2p.transport.quic.security import create_quic_security_transport
from libp2p.crypto.ed25519 import create_new_key_pair
from time import time
import os
import trio


async def test_full_handshake_and_certificate_exchange():
    """
    Test a full handshake to ensure it completes and peer certificates are exchanged.
    FIXED VERSION: Corrects connection ID management and address handling.
    """
    print("\n=== TESTING FULL HANDSHAKE AND CERTIFICATE EXCHANGE (FIXED) ===")

    # 1. Generate KeyPairs and create libp2p security configs for client and server.
    client_key_pair = create_new_key_pair()
    server_key_pair = create_new_key_pair()

    client_security_config = create_quic_security_transport(
        client_key_pair.private_key, ID.from_pubkey(client_key_pair.public_key)
    )
    server_security_config = create_quic_security_transport(
        server_key_pair.private_key, ID.from_pubkey(server_key_pair.public_key)
    )
    print("✅ libp2p security configs created.")

    # 2. Create aioquic configurations with consistent settings
    client_secrets_log_file = NamedTemporaryFile(
        mode="w", delete=False, suffix="-client.log"
    )
    client_aioquic_config = QuicConfiguration(
        is_client=True,
        alpn_protocols=["libp2p"],
        secrets_log_file=client_secrets_log_file,
        connection_id_length=8,  # Set consistent CID length
    )
    client_aioquic_config.certificate = client_security_config.tls_config.certificate
    client_aioquic_config.private_key = client_security_config.tls_config.private_key
    client_aioquic_config.verify_mode = (
        client_security_config.create_client_config().verify_mode
    )

    server_secrets_log_file = NamedTemporaryFile(
        mode="w", delete=False, suffix="-server.log"
    )
    server_aioquic_config = QuicConfiguration(
        is_client=False,
        alpn_protocols=["libp2p"],
        secrets_log_file=server_secrets_log_file,
        connection_id_length=8,  # Set consistent CID length
    )
    server_aioquic_config.certificate = server_security_config.tls_config.certificate
    server_aioquic_config.private_key = server_security_config.tls_config.private_key
    server_aioquic_config.verify_mode = (
        server_security_config.create_server_config().verify_mode
    )
    print("✅ aioquic configurations created and configured.")
    print(f"🔑 Client secrets will be logged to: {client_secrets_log_file.name}")
    print(f"🔑 Server secrets will be logged to: {server_secrets_log_file.name}")

    # 3. Use consistent addresses - this is crucial!
    # The client will connect TO the server address, but packets will come FROM client address
    client_address = ("127.0.0.1", 1234)  # Client binds to this
    server_address = ("127.0.0.1", 4321)  # Server binds to this

    # 4. Create client connection and initiate connection
    client_conn = QuicConnection(configuration=client_aioquic_config)
    # Client connects to server address - this sets up the initial packet with proper CIDs
    client_conn.connect(server_address, now=time())
    print("✅ Client connection initiated.")

    # 5. Get the initial client packet and extract ODCID properly
    client_datagrams = client_conn.datagrams_to_send(now=time())
    if not client_datagrams:
        raise AssertionError("❌ Client did not generate initial packet")

    client_initial_packet = client_datagrams[0][0]
    header = pull_quic_header(Buffer(data=client_initial_packet), host_cid_length=8)
    original_dcid = header.destination_cid
    client_source_cid = header.source_cid

    print(f"📊 Client ODCID: {original_dcid.hex()}")
    print(f"📊 Client source CID: {client_source_cid.hex()}")

    # 6. Create server connection with the correct ODCID
    server_conn = QuicConnection(
        configuration=server_aioquic_config,
        original_destination_connection_id=original_dcid,
    )
    print("✅ Server connection created with correct ODCID.")

    # 7. Feed the initial client packet to server
    # IMPORTANT: Use client_address as the source for the packet
    for datagram, _ in client_datagrams:
        header = pull_quic_header(Buffer(data=datagram))
        print(
            f"📤 Client -> Server: src={header.source_cid.hex()}, dst={header.destination_cid.hex()}"
        )
        server_conn.receive_datagram(datagram, client_address, now=time())

    # 8. Manual handshake loop with proper packet tracking
    max_duration_s = 3  # Increased timeout
    start_time = time()
    packet_count = 0

    while time() - start_time < max_duration_s:
        # Process client -> server packets
        client_packets = list(client_conn.datagrams_to_send(now=time()))
        for datagram, _ in client_packets:
            header = pull_quic_header(Buffer(data=datagram))
            print(
                f"📤 Client -> Server: src={header.source_cid.hex()}, dst={header.destination_cid.hex()}"
            )
            server_conn.receive_datagram(datagram, client_address, now=time())
            packet_count += 1

        # Process server -> client packets
        server_packets = list(server_conn.datagrams_to_send(now=time()))
        for datagram, _ in server_packets:
            header = pull_quic_header(Buffer(data=datagram))
            print(
                f"📤 Server -> Client: src={header.source_cid.hex()}, dst={header.destination_cid.hex()}"
            )
            # CRITICAL: Server sends back to client_address, not server_address
            client_conn.receive_datagram(datagram, server_address, now=time())
            packet_count += 1

        # Check for completion
        client_complete = getattr(client_conn, "_handshake_complete", False)
        server_complete = getattr(server_conn, "_handshake_complete", False)

        print(
            f"🔄 Handshake status: Client={client_complete}, Server={server_complete}, Packets={packet_count}"
        )

        if client_complete and server_complete:
            print("🎉 Handshake completed for both peers!")
            break

        # If no packets were exchanged in this iteration, wait a bit
        if not client_packets and not server_packets:
            await trio.sleep(0.01)

        # Safety check - if too many packets, something is wrong
        if packet_count > 50:
            print("⚠️ Too many packets exchanged, possible handshake loop")
            break

    # 9. Enhanced handshake completion checks
    client_handshake_complete = getattr(client_conn, "_handshake_complete", False)
    server_handshake_complete = getattr(server_conn, "_handshake_complete", False)

    # Debug additional state information
    print(f"🔍 Final client state: {getattr(client_conn, '_state', 'unknown')}")
    print(f"🔍 Final server state: {getattr(server_conn, '_state', 'unknown')}")

    if hasattr(client_conn, "tls") and client_conn.tls:
        print(f"🔍 Client TLS state: {getattr(client_conn.tls, 'state', 'unknown')}")
    if hasattr(server_conn, "tls") and server_conn.tls:
        print(f"🔍 Server TLS state: {getattr(server_conn.tls, 'state', 'unknown')}")

    # 10. Cleanup and assertions
    client_secrets_log_file.close()
    server_secrets_log_file.close()
    os.unlink(client_secrets_log_file.name)
    os.unlink(server_secrets_log_file.name)

    # Final assertions
    assert client_handshake_complete, (
        f"❌ Client handshake did not complete. "
        f"State: {getattr(client_conn, '_state', 'unknown')}, "
        f"Packets: {packet_count}"
    )
    assert server_handshake_complete, (
        f"❌ Server handshake did not complete. "
        f"State: {getattr(server_conn, '_state', 'unknown')}, "
        f"Packets: {packet_count}"
    )
    print("✅ Handshake completed for both peers.")

    # Certificate exchange verification
    client_peer_cert = getattr(client_conn.tls, "_peer_certificate", None)
    server_peer_cert = getattr(server_conn.tls, "_peer_certificate", None)

    assert client_peer_cert is not None, (
        "❌ Client FAILED to receive server certificate."
    )
    print("✅ Client successfully received server certificate.")

    assert server_peer_cert is not None, (
        "❌ Server FAILED to receive client certificate."
    )
    print("✅ Server successfully received client certificate.")

    print("🎉 Test Passed: Full handshake and certificate exchange successful.")
    return True

if __name__ == "__main__":
    trio.run(test_full_handshake_and_certificate_exchange)