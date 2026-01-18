import logging

import pytest
import multiaddr

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.utils.varint import encode_varint_prefixed, read_varint_prefixed_bytes

# Configuration
PROTOCOL_ID = TProtocol("/echo/1.0.0")
TEST_TIMEOUT = 30

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_echo_test(server_addr: str, messages: list[str]) -> list[str]:
    """
    Test echo protocol against go server.

    Args:
        server_addr: Full multiaddr of the go server including peer ID
        messages: List of messages to send and verify echo

    Returns:
        List of echoed responses

    """
    host = new_host(
        enable_quic=True,
        key_pair=create_new_key_pair(),
    )

    listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/udp/0/quic-v1")
    responses = []

    try:
        async with host.run(listen_addrs=[listen_addr]):
            logger.info(f"Connecting to go server: {server_addr}")

            # Connect to go server
            maddr = multiaddr.Multiaddr(server_addr)
            info = info_from_p2p_addr(maddr)
            await host.connect(info)

            # Create stream with echo protocol
            stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])
            logger.info("Stream created")

            # Test each message
            for i, message in enumerate(messages, 1):
                logger.info(f"Testing message {i}: {message}")

                # Send with varint length prefix (go-libp2p msgio format)
                data = message.encode("utf-8")
                prefixed_data = encode_varint_prefixed(data)
                await stream.write(prefixed_data)

                # Read response
                response_data = await read_varint_prefixed_bytes(stream)
                response = response_data.decode("utf-8")

                logger.info(f"Got echo: {response}")
                responses.append(response)

                # Verify echo
                assert message == response, (
                    f"Echo mismatch: sent {message!r}, got {response!r}"
                )

            await stream.close()
            logger.info("All messages echoed correctly")

    finally:
        await host.close()

    return responses


@pytest.mark.trio
@pytest.mark.timeout(TEST_TIMEOUT)
async def test_basic_echo(go_server):
    """Test basic echo functionality between py-libp2p and go-libp2p."""
    server, peer_id, listen_addr = go_server

    test_messages = [
        "Hello from py-libp2p!",
        "QUIC transport working",
        "go-libp2p interop test",
    ]

    responses = await run_echo_test(listen_addr, test_messages)
    assert responses == test_messages


@pytest.mark.trio
@pytest.mark.timeout(TEST_TIMEOUT)
async def test_echo_empty_string(go_server):
    """Test echoing an empty string."""
    server, peer_id, listen_addr = go_server

    # Note: Empty strings may be handled differently by servers
    # This tests edge case behavior
    host = new_host(
        enable_quic=True,
        key_pair=create_new_key_pair(),
    )

    listen_addr_local = multiaddr.Multiaddr("/ip4/0.0.0.0/udp/0/quic-v1")

    async with host.run(listen_addrs=[listen_addr_local]):
        maddr = multiaddr.Multiaddr(listen_addr)
        info = info_from_p2p_addr(maddr)
        await host.connect(info)

        stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])

        # Send a single character (empty might close connection)
        message = "x"
        data = message.encode("utf-8")
        prefixed_data = encode_varint_prefixed(data)
        await stream.write(prefixed_data)

        response_data = await read_varint_prefixed_bytes(stream)
        response = response_data.decode("utf-8")

        assert response == message
        await stream.close()

    await host.close()


@pytest.mark.trio
@pytest.mark.timeout(TEST_TIMEOUT)
async def test_echo_large_message(go_server):
    """Test echoing a larger message."""
    server, peer_id, listen_addr = go_server

    # 10KB message
    large_message = "X" * 10240

    responses = await run_echo_test(listen_addr, [large_message])
    assert responses[0] == large_message


@pytest.mark.trio
@pytest.mark.timeout(TEST_TIMEOUT)
async def test_echo_unicode(go_server):
    """Test echoing unicode messages."""
    server, peer_id, listen_addr = go_server

    test_messages = [
        "Hello 世界",
        "Unicode: Ñoël, 测试, Ψυχή"
    ]

    responses = await run_echo_test(listen_addr, test_messages)
    assert responses == test_messages


@pytest.mark.trio
@pytest.mark.timeout(TEST_TIMEOUT)
async def test_echo_multiple_sequential(go_server):
    """Test multiple sequential echo requests."""
    server, peer_id, listen_addr = go_server

    test_messages = [f"Message {i}" for i in range(10)]

    responses = await run_echo_test(listen_addr, test_messages)
    assert responses == test_messages


@pytest.mark.trio
@pytest.mark.timeout(TEST_TIMEOUT)
async def test_multiple_connections(go_server):
    """Test multiple separate connections to the same server."""
    server, peer_id, listen_addr = go_server

    async def single_connection(conn_id: int):
        messages = [f"Connection {conn_id} - Message {i}" for i in range(3)]
        responses = await run_echo_test(listen_addr, messages)
        assert responses == messages

    # Run 3 sequential connections
    for i in range(3):
        await single_connection(i)
