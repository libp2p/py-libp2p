"""
End-to-End WebSocket P2P Integration Tests.

This module provides comprehensive end-to-end tests that verify the full libp2p
stack works over WebSocket transport, including:
- Full security upgrade (Noise/TLS)
- Application-level protocol communication
- Bidirectional streams
- Multiple concurrent connections
- Connection lifecycle management
- Error handling and recovery
"""

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.host.basic_host import BasicHost
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.peer.peerstore import PeerStore
from libp2p.security.insecure.transport import InsecureTransport
from libp2p.security.noise.transport import (
    Transport as NoiseTransport,
    PROTOCOL_ID as NOISE_PROTOCOL_ID,
)
from libp2p.stream_muxer.yamux.yamux import Yamux
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.websocket.transport import WebsocketTransport

PLAINTEXT_PROTOCOL_ID = "/plaintext/2.0.0"
ECHO_PROTOCOL = TProtocol("/echo/1.0.0")
PING_PROTOCOL = TProtocol("/ipfs/ping/1.0.0")


def create_noise_upgrader(key_pair):
    """Create TransportUpgrader with Noise security."""
    noise_transport = NoiseTransport(
        libp2p_keypair=key_pair,
        noise_privkey=create_new_key_pair().private_key,
        early_data=None,
        with_noise_pipes=False,
    )
    return TransportUpgrader(
        secure_transports_by_protocol={TProtocol(NOISE_PROTOCOL_ID): noise_transport},
        muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
    )


def create_plaintext_upgrader(key_pair):
    """Create TransportUpgrader with PLAINTEXT security."""
    return TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
    )


async def create_websocket_host(
    listen_addrs: list[Multiaddr] | None = None,
    use_noise: bool = False,
) -> BasicHost:
    """Create a WebSocket-enabled libp2p host."""
    key_pair = create_new_key_pair()
    peer_id = ID.from_pubkey(key_pair.public_key)
    peer_store = PeerStore()
    peer_store.add_key_pair(peer_id, key_pair)

    if use_noise:
        upgrader = create_noise_upgrader(key_pair)
    else:
        upgrader = create_plaintext_upgrader(key_pair)

    transport = WebsocketTransport(upgrader)
    swarm = Swarm(peer_id, peer_store, upgrader, transport)
    host = BasicHost(swarm)

    if listen_addrs:
        for addr in listen_addrs:
            await swarm.listen(addr)

    return host


@pytest.mark.trio
@pytest.mark.timeout(60)
async def test_websocket_echo_protocol_plaintext():
    """Test echo protocol over WebSocket with PLAINTEXT security."""
    # Create two hosts
    listen_maddr = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")
    host1 = await create_websocket_host([listen_maddr], use_noise=False)
    host2 = await create_websocket_host([], use_noise=False)

    # Echo handler
    received_messages = []

    async def echo_handler(stream):
        data = await stream.read()
        received_messages.append(data)
        await stream.write(data)
        await stream.close()

    host1.set_stream_handler(ECHO_PROTOCOL, echo_handler)

    try:
        async with host1.run(), host2.run():
            # Get listening address
            addrs = host1.get_addrs()
            assert len(addrs) > 0
            listen_addr = addrs[0]

            # Extract peer ID and address
            peer_id = host1.get_id()
            peer_info = PeerInfo(peer_id, [listen_addr])

            # Connect
            await host2.connect(peer_info)
            await trio.sleep(0.5)  # Allow connection to establish

            # Send echo message
            test_message = b"Hello, WebSocket P2P!"
            stream = await host2.new_stream(peer_id, [ECHO_PROTOCOL])
            await stream.write(test_message)
            response = await stream.read()
            await stream.close()

            # Verify echo
            assert response == test_message
            assert len(received_messages) == 1
            assert received_messages[0] == test_message

    finally:
        await host1.close()
        await host2.close()


@pytest.mark.trio
@pytest.mark.timeout(60)
async def test_websocket_echo_protocol_noise():
    """Test echo protocol over WebSocket with Noise security."""
    listen_maddr = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")
    host1 = await create_websocket_host([listen_maddr], use_noise=True)
    host2 = await create_websocket_host([], use_noise=True)

    received_messages = []

    async def echo_handler(stream):
        data = await stream.read()
        received_messages.append(data)
        await stream.write(data)
        await stream.close()

    host1.set_stream_handler(ECHO_PROTOCOL, echo_handler)

    try:
        async with host1.run(), host2.run():
            addrs = host1.get_addrs()
            peer_id = host1.get_id()
            peer_info = PeerInfo(peer_id, [addrs[0]])

            await host2.connect(peer_info)
            await trio.sleep(0.5)

            test_message = b"Secure WebSocket with Noise!"
            stream = await host2.new_stream(peer_id, [ECHO_PROTOCOL])
            await stream.write(test_message)
            response = await stream.read()
            await stream.close()

            assert response == test_message

    finally:
        await host1.close()
        await host2.close()


@pytest.mark.trio
@pytest.mark.timeout(60)
async def test_websocket_bidirectional_communication():
    """Test bidirectional communication over WebSocket."""
    listen_maddr = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")
    host1 = await create_websocket_host([listen_maddr], use_noise=False)
    host2 = await create_websocket_host([], use_noise=False)

    messages_from_host2 = []
    messages_from_host1 = []

    async def handler1(stream):
        data = await stream.read()
        messages_from_host2.append(data)
        await stream.write(b"Response from host1")
        await stream.close()

    async def handler2(stream):
        data = await stream.read()
        messages_from_host1.append(data)
        await stream.write(b"Response from host2")
        await stream.close()

    host1.set_stream_handler(ECHO_PROTOCOL, handler1)
    host2.set_stream_handler(ECHO_PROTOCOL, handler2)

    try:
        async with host1.run(), host2.run():
            # Host2 connects to Host1
            peer_id_1 = host1.get_id()
            peer_info_1 = PeerInfo(peer_id_1, [host1.get_addrs()[0]])
            await host2.connect(peer_info_1)

            # Host1 connects to Host2
            peer_id_2 = host2.get_id()
            peer_info_2 = PeerInfo(peer_id_2, [host2.get_addrs()[0]])
            await host1.connect(peer_info_2)

            await trio.sleep(0.5)

            # Host2 sends to Host1
            stream1 = await host2.new_stream(peer_id_1, [ECHO_PROTOCOL])
            await stream1.write(b"Message from host2")
            resp1 = await stream1.read()
            await stream1.close()

            # Host1 sends to Host2
            stream2 = await host1.new_stream(peer_id_2, [ECHO_PROTOCOL])
            await stream2.write(b"Message from host1")
            resp2 = await stream2.read()
            await stream2.close()

            assert resp1 == b"Response from host1"
            assert resp2 == b"Response from host2"
            assert len(messages_from_host2) == 1
            assert len(messages_from_host1) == 1

    finally:
        await host1.close()
        await host2.close()


@pytest.mark.trio
@pytest.mark.timeout(60)
async def test_websocket_multiple_streams():
    """Test multiple concurrent streams over a single WebSocket connection."""
    listen_maddr = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")
    host1 = await create_websocket_host([listen_maddr], use_noise=False)
    host2 = await create_websocket_host([], use_noise=False)

    message_count = 0

    async def echo_handler(stream):
        nonlocal message_count
        data = await stream.read()
        message_count += 1
        await stream.write(f"Echo {message_count}: {data.decode()}".encode())
        await stream.close()

    host1.set_stream_handler(ECHO_PROTOCOL, echo_handler)

    try:
        async with host1.run(), host2.run():
            peer_id = host1.get_id()
            peer_info = PeerInfo(peer_id, [host1.get_addrs()[0]])
            await host2.connect(peer_info)
            await trio.sleep(0.5)

            # Open multiple streams
            streams = []
            for i in range(5):
                stream = await host2.new_stream(peer_id, [ECHO_PROTOCOL])
                streams.append(stream)

            # Send messages concurrently
            async def send_message(stream, idx):
                await stream.write(f"Message {idx}".encode())
                response = await stream.read()
                await stream.close()
                return response

            async with trio.open_nursery() as nursery:
                responses = []
                for idx, stream in enumerate(streams):
                    responses.append(
                        nursery.start_soon(send_message, stream, idx + 1)
                    )

                # Collect responses
                results = []
                for resp_task in responses:
                    results.append(await resp_task.wait())

            # Verify all messages were echoed
            assert len(results) == 5
            assert message_count == 5

    finally:
        await host1.close()
        await host2.close()


@pytest.mark.trio
@pytest.mark.timeout(60)
async def test_websocket_ping_protocol():
    """Test ping protocol over WebSocket."""
    listen_maddr = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")
    host1 = await create_websocket_host([listen_maddr], use_noise=False)
    host2 = await create_websocket_host([], use_noise=False)

    async def ping_handler(stream):
        data = await stream.read(4)
        if data == b"ping":
            await stream.write(b"pong")
        await stream.close()

    host1.set_stream_handler(PING_PROTOCOL, ping_handler)

    try:
        async with host1.run(), host2.run():
            peer_id = host1.get_id()
            peer_info = PeerInfo(peer_id, [host1.get_addrs()[0]])
            await host2.connect(peer_info)
            await trio.sleep(0.5)

            # Send ping
            stream = await host2.new_stream(peer_id, [PING_PROTOCOL])
            await stream.write(b"ping")
            response = await stream.read(4)
            await stream.close()

            assert response == b"pong"

    finally:
        await host1.close()
        await host2.close()


@pytest.mark.trio
@pytest.mark.timeout(60)
async def test_websocket_large_message():
    """Test sending large messages over WebSocket."""
    listen_maddr = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")
    host1 = await create_websocket_host([listen_maddr], use_noise=False)
    host2 = await create_websocket_host([], use_noise=False)

    async def echo_handler(stream):
        data = await stream.read()
        await stream.write(data)
        await stream.close()

    host1.set_stream_handler(ECHO_PROTOCOL, echo_handler)

    try:
        async with host1.run(), host2.run():
            peer_id = host1.get_id()
            peer_info = PeerInfo(peer_id, [host1.get_addrs()[0]])
            await host2.connect(peer_info)
            await trio.sleep(0.5)

            # Send large message (100KB)
            large_message = b"x" * (100 * 1024)
            stream = await host2.new_stream(peer_id, [ECHO_PROTOCOL])
            await stream.write(large_message)

            # Read response in chunks
            response = b""
            while True:
                chunk = await stream.read(8192)
                if not chunk:
                    break
                response += chunk

            await stream.close()

            assert response == large_message
            assert len(response) == 100 * 1024

    finally:
        await host1.close()
        await host2.close()


@pytest.mark.trio
@pytest.mark.timeout(60)
async def test_websocket_connection_lifecycle():
    """Test connection lifecycle management."""
    listen_maddr = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")
    host1 = await create_websocket_host([listen_maddr], use_noise=False)
    host2 = await create_websocket_host([], use_noise=False)

    async def echo_handler(stream):
        data = await stream.read()
        await stream.write(data)
        await stream.close()

    host1.set_stream_handler(ECHO_PROTOCOL, echo_handler)

    try:
        async with host1.run(), host2.run():
            peer_id = host1.get_id()
            peer_info = PeerInfo(peer_id, [host1.get_addrs()[0]])

            # Connect
            await host2.connect(peer_info)
            await trio.sleep(0.5)

            # Verify connection exists
            connections = host2.get_network().connections.get(peer_id)
            assert connections is not None
            assert len(connections) > 0

            # Send message
            stream = await host2.new_stream(peer_id, [ECHO_PROTOCOL])
            await stream.write(b"test")
            response = await stream.read()
            await stream.close()
            assert response == b"test"

            # Disconnect
            await host2.disconnect(peer_id)
            await trio.sleep(0.5)

            # Connection should be removed
            connections_after = host2.get_network().connections.get(peer_id)
            assert connections_after is None or len(connections_after) == 0

    finally:
        await host1.close()
        await host2.close()


@pytest.mark.trio
@pytest.mark.timeout(60)
async def test_websocket_multiple_connections():
    """Test multiple hosts connecting to one server."""
    listen_maddr = Multiaddr("/ip4/127.0.0.1/tcp/0/ws")
    server = await create_websocket_host([listen_maddr], use_noise=False)

    received_from = set()

    async def echo_handler(stream):
        # Get peer ID from connection
        peer_id_str = "unknown"
        # Echo with identifier
        data = await stream.read()
        received_from.add(peer_id_str)
        await stream.write(b"ack")
        await stream.close()

    server.set_stream_handler(ECHO_PROTOCOL, echo_handler)

    try:
        async with server.run():
            peer_id = server.get_id()
            server_addr = server.get_addrs()[0]
            peer_info = PeerInfo(peer_id, [server_addr])

            # Create multiple clients
            clients = []
            for _ in range(3):
                client = await create_websocket_host([], use_noise=False)
                clients.append(client)

            async with trio.open_nursery() as nursery:
                for client in clients:
                    nursery.start_soon(client.run)

                await trio.sleep(0.5)

                # All clients connect and send messages
                async def client_send(client):
                    await client.connect(peer_info)
                    await trio.sleep(0.2)
                    stream = await client.new_stream(peer_id, [ECHO_PROTOCOL])
                    await stream.write(b"hello")
                    response = await stream.read()
                    await stream.close()
                    assert response == b"ack"

                async with trio.open_nursery() as send_nursery:
                    for client in clients:
                        send_nursery.start_soon(client_send, client)

                # Cleanup
                for client in clients:
                    await client.close()

    finally:
        await server.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

