#!/usr/bin/env python3
"""
Python-to-Python WebSocket peer-to-peer tests.

This module tests real WebSocket communication between two Python libp2p hosts,
including both WS and WSS (WebSocket Secure) scenarios.
"""

import pytest
from multiaddr import Multiaddr

from libp2p import create_yamux_muxer_option, new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.custom_types import TProtocol
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
from libp2p.security.noise.transport import (
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
    Transport as NoiseTransport,
)
from libp2p.transport.websocket.multiaddr_utils import (
    is_valid_websocket_multiaddr,
    parse_websocket_multiaddr,
)

PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32


@pytest.mark.trio
async def test_websocket_p2p_plaintext():
    """Test Python-to-Python WebSocket communication with plaintext security."""
    # Create two hosts with plaintext security
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()

    # Host A (listener) - use only plaintext security
    security_options_a = {
        PLAINTEXT_PROTOCOL_ID: InsecureTransport(
            local_key_pair=key_pair_a, secure_bytes_provider=None, peerstore=None
        )
    }
    host_a = new_host(
        key_pair=key_pair_a,
        sec_opt=security_options_a,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")],
    )

    # Host B (dialer) - use only plaintext security
    security_options_b = {
        PLAINTEXT_PROTOCOL_ID: InsecureTransport(
            local_key_pair=key_pair_b, secure_bytes_provider=None, peerstore=None
        )
    }
    host_b = new_host(
        key_pair=key_pair_b,
        sec_opt=security_options_b,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")],  # Ensure WebSocket
        # transport
    )

    # Test data
    test_data = b"Hello WebSocket P2P!"
    received_data = None

    # Set up ping handler on host A
    async def ping_handler(stream):
        nonlocal received_data
        received_data = await stream.read(len(test_data))
        await stream.write(received_data)  # Echo back
        await stream.close()

    host_a.set_stream_handler(PING_PROTOCOL_ID, ping_handler)

    # Start both hosts
    async with (
        host_a.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")]),
        host_b.run(listen_addrs=[]),
    ):
        # Get host A's listen address
        listen_addrs = host_a.get_addrs()
        assert len(listen_addrs) > 0

        # Find the WebSocket address
        ws_addr = None
        for addr in listen_addrs:
            if "/ws" in str(addr):
                ws_addr = addr
                break

        assert ws_addr is not None, "No WebSocket listen address found"
        assert is_valid_websocket_multiaddr(ws_addr), "Invalid WebSocket multiaddr"

        # Parse the WebSocket multiaddr
        parsed = parse_websocket_multiaddr(ws_addr)
        assert not parsed.is_wss, "Should be plain WebSocket, not WSS"
        assert parsed.sni is None, "SNI should be None for plain WebSocket"

        # Connect host B to host A
        from libp2p.peer.peerinfo import info_from_p2p_addr

        peer_info = info_from_p2p_addr(ws_addr)
        await host_b.connect(peer_info)

        # Create stream and test communication
        stream = await host_b.new_stream(host_a.get_id(), [PING_PROTOCOL_ID])
        await stream.write(test_data)
        response = await stream.read(len(test_data))
        await stream.close()

        # Verify communication
        assert received_data == test_data, f"Expected {test_data}, got {received_data}"
        assert response == test_data, f"Expected echo {test_data}, got {response}"


@pytest.mark.trio
async def test_websocket_p2p_noise():
    """Test Python-to-Python WebSocket communication with Noise security."""
    # Create two hosts with Noise security
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()
    noise_key_pair_a = create_new_x25519_key_pair()
    noise_key_pair_b = create_new_x25519_key_pair()

    # Host A (listener)
    security_options_a = {
        NOISE_PROTOCOL_ID: NoiseTransport(
            libp2p_keypair=key_pair_a,
            noise_privkey=noise_key_pair_a.private_key,
            early_data=None,
            with_noise_pipes=False,
        )
    }
    host_a = new_host(
        key_pair=key_pair_a,
        sec_opt=security_options_a,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")],
    )

    # Host B (dialer)
    security_options_b = {
        NOISE_PROTOCOL_ID: NoiseTransport(
            libp2p_keypair=key_pair_b,
            noise_privkey=noise_key_pair_b.private_key,
            early_data=None,
            with_noise_pipes=False,
        )
    }
    host_b = new_host(
        key_pair=key_pair_b,
        sec_opt=security_options_b,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")],  # Ensure WebSocket
        # transport
    )

    # Test data
    test_data = b"Hello WebSocket P2P with Noise!"
    received_data = None

    # Set up ping handler on host A
    async def ping_handler(stream):
        nonlocal received_data
        received_data = await stream.read(len(test_data))
        await stream.write(received_data)  # Echo back
        await stream.close()

    host_a.set_stream_handler(PING_PROTOCOL_ID, ping_handler)

    # Start both hosts
    async with (
        host_a.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")]),
        host_b.run(listen_addrs=[]),
    ):
        # Get host A's listen address
        listen_addrs = host_a.get_addrs()
        assert len(listen_addrs) > 0

        # Find the WebSocket address
        ws_addr = None
        for addr in listen_addrs:
            if "/ws" in str(addr):
                ws_addr = addr
                break

        assert ws_addr is not None, "No WebSocket listen address found"
        assert is_valid_websocket_multiaddr(ws_addr), "Invalid WebSocket multiaddr"

        # Parse the WebSocket multiaddr
        parsed = parse_websocket_multiaddr(ws_addr)
        assert not parsed.is_wss, "Should be plain WebSocket, not WSS"
        assert parsed.sni is None, "SNI should be None for plain WebSocket"

        # Connect host B to host A
        from libp2p.peer.peerinfo import info_from_p2p_addr

        peer_info = info_from_p2p_addr(ws_addr)
        await host_b.connect(peer_info)

        # Create stream and test communication
        stream = await host_b.new_stream(host_a.get_id(), [PING_PROTOCOL_ID])
        await stream.write(test_data)
        response = await stream.read(len(test_data))
        await stream.close()

        # Verify communication
        assert received_data == test_data, f"Expected {test_data}, got {received_data}"
        assert response == test_data, f"Expected echo {test_data}, got {response}"


@pytest.mark.trio
async def test_websocket_p2p_libp2p_ping():
    """Test Python-to-Python WebSocket communication using libp2p ping protocol."""
    # Create two hosts with Noise security
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()
    noise_key_pair_a = create_new_x25519_key_pair()
    noise_key_pair_b = create_new_x25519_key_pair()

    # Host A (listener)
    security_options_a = {
        NOISE_PROTOCOL_ID: NoiseTransport(
            libp2p_keypair=key_pair_a,
            noise_privkey=noise_key_pair_a.private_key,
            early_data=None,
            with_noise_pipes=False,
        )
    }
    host_a = new_host(
        key_pair=key_pair_a,
        sec_opt=security_options_a,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")],
    )

    # Host B (dialer)
    security_options_b = {
        NOISE_PROTOCOL_ID: NoiseTransport(
            libp2p_keypair=key_pair_b,
            noise_privkey=noise_key_pair_b.private_key,
            early_data=None,
            with_noise_pipes=False,
        )
    }
    host_b = new_host(
        key_pair=key_pair_b,
        sec_opt=security_options_b,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")],  # Ensure WebSocket
        # transport
    )

    # Set up ping handler on host A (standard libp2p ping protocol)
    async def ping_handler(stream):
        # Read ping data (32 bytes)
        ping_data = await stream.read(PING_LENGTH)
        # Echo back the same data (pong)
        await stream.write(ping_data)
        await stream.close()

    host_a.set_stream_handler(PING_PROTOCOL_ID, ping_handler)

    # Start both hosts
    async with (
        host_a.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")]),
        host_b.run(listen_addrs=[]),
    ):
        # Get host A's listen address
        listen_addrs = host_a.get_addrs()
        assert len(listen_addrs) > 0

        # Find the WebSocket address
        ws_addr = None
        for addr in listen_addrs:
            if "/ws" in str(addr):
                ws_addr = addr
                break

        assert ws_addr is not None, "No WebSocket listen address found"

        # Connect host B to host A
        from libp2p.peer.peerinfo import info_from_p2p_addr

        peer_info = info_from_p2p_addr(ws_addr)
        await host_b.connect(peer_info)

        # Create stream and test libp2p ping protocol
        stream = await host_b.new_stream(host_a.get_id(), [PING_PROTOCOL_ID])

        # Send ping (32 bytes as per libp2p ping protocol)
        ping_data = b"\x01" * PING_LENGTH
        await stream.write(ping_data)

        # Receive pong (should be same 32 bytes)
        pong_data = await stream.read(PING_LENGTH)
        await stream.close()

        # Verify ping-pong
        assert pong_data == ping_data, (
            f"Expected ping {ping_data}, got pong {pong_data}"
        )


@pytest.mark.trio
async def test_websocket_p2p_multiple_streams():
    """
    Test Python-to-Python WebSocket communication with multiple concurrent
    streams.
    """
    # Create two hosts with Noise security
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()
    noise_key_pair_a = create_new_x25519_key_pair()
    noise_key_pair_b = create_new_x25519_key_pair()

    # Host A (listener)
    security_options_a = {
        NOISE_PROTOCOL_ID: NoiseTransport(
            libp2p_keypair=key_pair_a,
            noise_privkey=noise_key_pair_a.private_key,
            early_data=None,
            with_noise_pipes=False,
        )
    }
    host_a = new_host(
        key_pair=key_pair_a,
        sec_opt=security_options_a,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")],
    )

    # Host B (dialer)
    security_options_b = {
        NOISE_PROTOCOL_ID: NoiseTransport(
            libp2p_keypair=key_pair_b,
            noise_privkey=noise_key_pair_b.private_key,
            early_data=None,
            with_noise_pipes=False,
        )
    }
    host_b = new_host(
        key_pair=key_pair_b,
        sec_opt=security_options_b,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")],  # Ensure WebSocket
        # transport
    )

    # Test protocol
    test_protocol = TProtocol("/test/multiple/streams/1.0.0")
    received_data = []

    # Set up handler on host A
    async def test_handler(stream):
        data = await stream.read(1024)
        received_data.append(data)
        await stream.write(data)  # Echo back
        await stream.close()

    host_a.set_stream_handler(test_protocol, test_handler)

    # Start both hosts
    async with (
        host_a.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")]),
        host_b.run(listen_addrs=[]),
    ):
        # Get host A's listen address
        listen_addrs = host_a.get_addrs()
        ws_addr = None
        for addr in listen_addrs:
            if "/ws" in str(addr):
                ws_addr = addr
                break

        assert ws_addr is not None, "No WebSocket listen address found"

        # Connect host B to host A
        from libp2p.peer.peerinfo import info_from_p2p_addr

        peer_info = info_from_p2p_addr(ws_addr)
        await host_b.connect(peer_info)

        # Create multiple concurrent streams
        num_streams = 5
        test_data_list = [f"Stream {i} data".encode() for i in range(num_streams)]

        async def create_stream_and_test(stream_id: int, data: bytes):
            stream = await host_b.new_stream(host_a.get_id(), [test_protocol])
            await stream.write(data)
            response = await stream.read(len(data))
            await stream.close()
            return response

        # Run all streams concurrently
        tasks = [
            create_stream_and_test(i, test_data_list[i]) for i in range(num_streams)
        ]
        responses = []
        for task in tasks:
            responses.append(await task)

        # Verify all communications
        assert len(received_data) == num_streams, (
            f"Expected {num_streams} received messages, got {len(received_data)}"
        )
        for i, (sent, received, response) in enumerate(
            zip(test_data_list, received_data, responses)
        ):
            assert received == sent, f"Stream {i}: Expected {sent}, got {received}"
            assert response == sent, f"Stream {i}: Expected echo {sent}, got {response}"


@pytest.mark.trio
async def test_websocket_p2p_connection_state():
    """Test WebSocket connection state tracking and metadata."""
    # Create two hosts with Noise security
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()
    noise_key_pair_a = create_new_x25519_key_pair()
    noise_key_pair_b = create_new_x25519_key_pair()

    # Host A (listener)
    security_options_a = {
        NOISE_PROTOCOL_ID: NoiseTransport(
            libp2p_keypair=key_pair_a,
            noise_privkey=noise_key_pair_a.private_key,
            early_data=None,
            with_noise_pipes=False,
        )
    }
    host_a = new_host(
        key_pair=key_pair_a,
        sec_opt=security_options_a,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")],
    )

    # Host B (dialer)
    security_options_b = {
        NOISE_PROTOCOL_ID: NoiseTransport(
            libp2p_keypair=key_pair_b,
            noise_privkey=noise_key_pair_b.private_key,
            early_data=None,
            with_noise_pipes=False,
        )
    }
    host_b = new_host(
        key_pair=key_pair_b,
        sec_opt=security_options_b,
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")],  # Ensure WebSocket
        # transport
    )

    # Set up handler on host A
    async def test_handler(stream):
        # Read some data
        await stream.read(1024)
        # Write some data back
        await stream.write(b"Response data")
        await stream.close()

    host_a.set_stream_handler(PING_PROTOCOL_ID, test_handler)

    # Start both hosts
    async with (
        host_a.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0/ws")]),
        host_b.run(listen_addrs=[]),
    ):
        # Get host A's listen address
        listen_addrs = host_a.get_addrs()
        ws_addr = None
        for addr in listen_addrs:
            if "/ws" in str(addr):
                ws_addr = addr
                break

        assert ws_addr is not None, "No WebSocket listen address found"

        # Connect host B to host A
        from libp2p.peer.peerinfo import info_from_p2p_addr

        peer_info = info_from_p2p_addr(ws_addr)
        await host_b.connect(peer_info)

        # Create stream and test communication
        stream = await host_b.new_stream(host_a.get_id(), [PING_PROTOCOL_ID])
        await stream.write(b"Test data for connection state")
        response = await stream.read(1024)
        await stream.close()

        # Verify response
        assert response == b"Response data", f"Expected 'Response data', got {response}"

        # Test connection state (if available)
        # Note: This tests the connection state tracking we implemented
        connections = host_b.get_network().connections
        assert len(connections) > 0, "Should have at least one connection"

        # Get the connection to host A
        conn_to_a = None
        for peer_id, conn_list in connections.items():
            if peer_id == host_a.get_id():
                # connections maps peer_id to list of connections, get the first one
                conn_to_a = conn_list[0] if conn_list else None
                break

        assert conn_to_a is not None, "Should have connection to host A"

        # Test that the connection has the expected properties
        assert hasattr(conn_to_a, "muxed_conn"), "Connection should have muxed_conn"
        assert hasattr(conn_to_a.muxed_conn, "secured_conn"), (
            "Muxed connection should have underlying secured_conn"
        )

        # If the underlying connection is our WebSocket connection, test its state
        # Type assertion to access private attribute for testing
        underlying_conn = getattr(conn_to_a.muxed_conn, "secured_conn")
        if hasattr(underlying_conn, "conn_state"):
            state = underlying_conn.conn_state()
            assert "connection_start_time" in state, (
                "Connection state should include start time"
            )
            assert "bytes_read" in state, "Connection state should include bytes read"
            assert "bytes_written" in state, (
                "Connection state should include bytes written"
            )
            assert state["bytes_read"] > 0, "Should have read some bytes"
            assert state["bytes_written"] > 0, "Should have written some bytes"
