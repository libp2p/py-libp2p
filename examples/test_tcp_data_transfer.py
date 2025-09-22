#!/usr/bin/env python3
"""
TCP P2P Data Transfer Test

This test proves that TCP peer-to-peer data transfer works correctly in libp2p.
This serves as a baseline to compare with WebSocket tests.
"""

import pytest
from multiaddr import Multiaddr
import trio

from libp2p import create_yamux_muxer_option, new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport

# Test protocol for data exchange
TCP_DATA_PROTOCOL = TProtocol("/test/tcp-data-exchange/1.0.0")


async def create_tcp_host_pair():
    """Create a pair of hosts configured for TCP communication."""
    # Create key pairs
    key_pair_a = create_new_key_pair()
    key_pair_b = create_new_key_pair()

    # Create security options (using plaintext for simplicity)
    def security_options(kp):
        return {
            PLAINTEXT_PROTOCOL_ID: InsecureTransport(
                local_key_pair=kp, secure_bytes_provider=None, peerstore=None
            )
        }

    # Host A (listener) - TCP transport (default)
    host_a = new_host(
        key_pair=key_pair_a,
        sec_opt=security_options(key_pair_a),
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    # Host B (dialer) - TCP transport (default)
    host_b = new_host(
        key_pair=key_pair_b,
        sec_opt=security_options(key_pair_b),
        muxer_opt=create_yamux_muxer_option(),
        listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")],
    )

    return host_a, host_b


@pytest.mark.trio
async def test_tcp_basic_connection():
    """Test basic TCP connection establishment."""
    host_a, host_b = await create_tcp_host_pair()

    connection_established = False

    async def connection_handler(stream):
        nonlocal connection_established
        connection_established = True
        await stream.close()

    host_a.set_stream_handler(TCP_DATA_PROTOCOL, connection_handler)

    async with (
        host_a.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")]),
        host_b.run(listen_addrs=[]),
    ):
        # Get host A's listen address
        listen_addrs = host_a.get_addrs()
        assert listen_addrs, "Host A should have listen addresses"

        # Extract TCP address
        tcp_addr = None
        for addr in listen_addrs:
            if "/tcp/" in str(addr) and "/ws" not in str(addr):
                tcp_addr = addr
                break

        assert tcp_addr, f"No TCP address found in {listen_addrs}"
        print(f"🔗 Host A listening on: {tcp_addr}")

        # Create peer info for host A
        peer_info = info_from_p2p_addr(tcp_addr)

        # Host B connects to host A
        await host_b.connect(peer_info)
        print("✅ TCP connection established")

        # Open a stream to test the connection
        stream = await host_b.new_stream(peer_info.peer_id, [TCP_DATA_PROTOCOL])
        await stream.close()

        # Wait a bit for the handler to be called
        await trio.sleep(0.1)

        assert connection_established, "TCP connection handler should have been called"
        print("✅ TCP basic connection test successful!")


@pytest.mark.trio
async def test_tcp_data_transfer():
    """Test TCP peer-to-peer data transfer."""
    host_a, host_b = await create_tcp_host_pair()

    # Test data
    test_data = b"Hello TCP P2P Data Transfer! This is a test message."
    received_data = None
    transfer_complete = trio.Event()

    async def data_handler(stream):
        nonlocal received_data
        try:
            # Read the incoming data
            received_data = await stream.read(len(test_data))
            # Echo it back to confirm successful transfer
            await stream.write(received_data)
            await stream.close()
            transfer_complete.set()
        except Exception as e:
            print(f"Handler error: {e}")
            transfer_complete.set()

    host_a.set_stream_handler(TCP_DATA_PROTOCOL, data_handler)

    async with (
        host_a.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")]),
        host_b.run(listen_addrs=[]),
    ):
        # Get host A's listen address
        listen_addrs = host_a.get_addrs()
        assert listen_addrs, "Host A should have listen addresses"

        # Extract TCP address
        tcp_addr = None
        for addr in listen_addrs:
            if "/tcp/" in str(addr) and "/ws" not in str(addr):
                tcp_addr = addr
                break

        assert tcp_addr, f"No TCP address found in {listen_addrs}"
        print(f"🔗 Host A listening on: {tcp_addr}")

        # Create peer info for host A
        peer_info = info_from_p2p_addr(tcp_addr)

        # Host B connects to host A
        await host_b.connect(peer_info)
        print("✅ TCP connection established")

        # Open a stream for data transfer
        stream = await host_b.new_stream(peer_info.peer_id, [TCP_DATA_PROTOCOL])
        print("✅ TCP stream opened")

        # Send test data
        await stream.write(test_data)
        print(f"📤 Sent data: {test_data}")

        # Read echoed data back
        echoed_data = await stream.read(len(test_data))
        print(f"📥 Received echo: {echoed_data}")

        await stream.close()

        # Wait for transfer to complete
        with trio.fail_after(5.0):  # 5 second timeout
            await transfer_complete.wait()

        # Verify data transfer
        assert received_data == test_data, (
            f"Data mismatch: {received_data} != {test_data}"
        )
        assert echoed_data == test_data, f"Echo mismatch: {echoed_data} != {test_data}"

        print("✅ TCP P2P data transfer successful!")
        print(f"   Original:  {test_data}")
        print(f"   Received:  {received_data}")
        print(f"   Echoed:    {echoed_data}")


@pytest.mark.trio
async def test_tcp_large_data_transfer():
    """Test TCP with larger data payloads."""
    host_a, host_b = await create_tcp_host_pair()

    # Large test data (10KB)
    test_data = b"TCP Large Data Test! " * 500  # ~10KB
    received_data = None
    transfer_complete = trio.Event()

    async def large_data_handler(stream):
        nonlocal received_data
        try:
            # Read data in chunks
            chunks = []
            total_received = 0
            expected_size = len(test_data)

            while total_received < expected_size:
                chunk = await stream.read(min(1024, expected_size - total_received))
                if not chunk:
                    break
                chunks.append(chunk)
                total_received += len(chunk)

            received_data = b"".join(chunks)

            # Send back confirmation
            await stream.write(b"RECEIVED_OK")
            await stream.close()
            transfer_complete.set()
        except Exception as e:
            print(f"Large data handler error: {e}")
            transfer_complete.set()

    host_a.set_stream_handler(TCP_DATA_PROTOCOL, large_data_handler)

    async with (
        host_a.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")]),
        host_b.run(listen_addrs=[]),
    ):
        # Get host A's listen address
        listen_addrs = host_a.get_addrs()
        assert listen_addrs, "Host A should have listen addresses"

        # Extract TCP address
        tcp_addr = None
        for addr in listen_addrs:
            if "/tcp/" in str(addr) and "/ws" not in str(addr):
                tcp_addr = addr
                break

        assert tcp_addr, f"No TCP address found in {listen_addrs}"
        print(f"🔗 Host A listening on: {tcp_addr}")
        print(f"📊 Test data size: {len(test_data)} bytes")

        # Create peer info for host A
        peer_info = info_from_p2p_addr(tcp_addr)

        # Host B connects to host A
        await host_b.connect(peer_info)
        print("✅ TCP connection established")

        # Open a stream for data transfer
        stream = await host_b.new_stream(peer_info.peer_id, [TCP_DATA_PROTOCOL])
        print("✅ TCP stream opened")

        # Send large test data in chunks
        chunk_size = 1024
        sent_bytes = 0
        for i in range(0, len(test_data), chunk_size):
            chunk = test_data[i : i + chunk_size]
            await stream.write(chunk)
            sent_bytes += len(chunk)
            if sent_bytes % (chunk_size * 4) == 0:  # Progress every 4KB
                print(f"📤 Sent {sent_bytes}/{len(test_data)} bytes")

        print(f"📤 Sent all {len(test_data)} bytes")

        # Read confirmation
        confirmation = await stream.read(1024)
        print(f"📥 Received confirmation: {confirmation}")

        await stream.close()

        # Wait for transfer to complete
        with trio.fail_after(10.0):  # 10 second timeout for large data
            await transfer_complete.wait()

        # Verify data transfer
        assert received_data is not None, "No data was received"
        assert received_data == test_data, (
            "Large data transfer failed:"
            + f" sizes {len(received_data)} != {len(test_data)}"
        )
        assert confirmation == b"RECEIVED_OK", f"Confirmation failed: {confirmation}"

        print("✅ TCP large data transfer successful!")
        print(f"   Data size: {len(test_data)} bytes")
        print(f"   Received:  {len(received_data)} bytes")
        print(f"   Match:     {received_data == test_data}")


@pytest.mark.trio
async def test_tcp_bidirectional_transfer():
    """Test bidirectional data transfer over TCP."""
    host_a, host_b = await create_tcp_host_pair()

    # Test data
    data_a_to_b = b"Message from Host A to Host B via TCP"
    data_b_to_a = b"Response from Host B to Host A via TCP"

    received_on_a = None
    received_on_b = None
    transfer_complete_a = trio.Event()
    transfer_complete_b = trio.Event()

    async def handler_a(stream):
        nonlocal received_on_a
        try:
            # Read data from B
            received_on_a = await stream.read(len(data_b_to_a))
            print(f"🅰️  Host A received: {received_on_a}")
            await stream.close()
            transfer_complete_a.set()
        except Exception as e:
            print(f"Handler A error: {e}")
            transfer_complete_a.set()

    async def handler_b(stream):
        nonlocal received_on_b
        try:
            # Read data from A
            received_on_b = await stream.read(len(data_a_to_b))
            print(f"🅱️  Host B received: {received_on_b}")
            await stream.close()
            transfer_complete_b.set()
        except Exception as e:
            print(f"Handler B error: {e}")
            transfer_complete_b.set()

    # Set up handlers on both hosts
    protocol_a_to_b = TProtocol("/test/tcp-a-to-b/1.0.0")
    protocol_b_to_a = TProtocol("/test/tcp-b-to-a/1.0.0")

    host_a.set_stream_handler(protocol_b_to_a, handler_a)
    host_b.set_stream_handler(protocol_a_to_b, handler_b)

    async with (
        host_a.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")]),
        host_b.run(listen_addrs=[Multiaddr("/ip4/127.0.0.1/tcp/0")]),
    ):
        # Get addresses
        addrs_a = host_a.get_addrs()
        addrs_b = host_b.get_addrs()

        assert addrs_a and addrs_b, "Both hosts should have addresses"

        # Extract TCP addresses
        tcp_addr_a = next(
            (
                addr
                for addr in addrs_a
                if "/tcp/" in str(addr) and "/ws" not in str(addr)
            ),
            None,
        )
        tcp_addr_b = next(
            (
                addr
                for addr in addrs_b
                if "/tcp/" in str(addr) and "/ws" not in str(addr)
            ),
            None,
        )

        assert tcp_addr_a and tcp_addr_b, (
            f"TCP addresses not found: A={addrs_a}, B={addrs_b}"
        )
        print(f"🔗 Host A listening on: {tcp_addr_a}")
        print(f"🔗 Host B listening on: {tcp_addr_b}")

        # Create peer infos
        peer_info_a = info_from_p2p_addr(tcp_addr_a)
        peer_info_b = info_from_p2p_addr(tcp_addr_b)

        # Establish connections
        await host_b.connect(peer_info_a)
        await host_a.connect(peer_info_b)
        print("✅ Bidirectional TCP connections established")

        # Send data A -> B
        stream_a_to_b = await host_a.new_stream(peer_info_b.peer_id, [protocol_a_to_b])
        await stream_a_to_b.write(data_a_to_b)
        print(f"📤 A->B: {data_a_to_b}")
        await stream_a_to_b.close()

        # Send data B -> A
        stream_b_to_a = await host_b.new_stream(peer_info_a.peer_id, [protocol_b_to_a])
        await stream_b_to_a.write(data_b_to_a)
        print(f"📤 B->A: {data_b_to_a}")
        await stream_b_to_a.close()

        # Wait for both transfers to complete
        with trio.fail_after(5.0):
            await transfer_complete_a.wait()
            await transfer_complete_b.wait()

        # Verify bidirectional transfer
        assert received_on_a == data_b_to_a, f"A received wrong data: {received_on_a}"
        assert received_on_b == data_a_to_b, f"B received wrong data: {received_on_b}"

        print("✅ TCP bidirectional data transfer successful!")
        print(f"   A->B: {data_a_to_b}")
        print(f"   B->A: {data_b_to_a}")
        print(f"   ✓ A got: {received_on_a}")
        print(f"   ✓ B got: {received_on_b}")


if __name__ == "__main__":
    # Run tests directly
    import logging

    logging.basicConfig(level=logging.INFO)

    print("🧪 Running TCP P2P Data Transfer Tests")
    print("=" * 50)

    async def run_all_tcp_tests():
        try:
            print("\n1. Testing basic TCP connection...")
            await test_tcp_basic_connection()
        except Exception as e:
            print(f"❌ Basic TCP connection test failed: {e}")
            return

        try:
            print("\n2. Testing TCP data transfer...")
            await test_tcp_data_transfer()
        except Exception as e:
            print(f"❌ TCP data transfer test failed: {e}")
            return

        try:
            print("\n3. Testing TCP large data transfer...")
            await test_tcp_large_data_transfer()
        except Exception as e:
            print(f"❌ TCP large data transfer test failed: {e}")
            return

        try:
            print("\n4. Testing TCP bidirectional transfer...")
            await test_tcp_bidirectional_transfer()
        except Exception as e:
            print(f"❌ TCP bidirectional transfer test failed: {e}")
            return

        print("\n" + "=" * 50)
        print("🏁 TCP P2P Tests Complete - All Tests PASSED!")

    trio.run(run_all_tcp_tests)
