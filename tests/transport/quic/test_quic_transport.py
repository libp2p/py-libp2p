import asyncio

import pytest

from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.transport.exceptions import (
    TransportError,
)
from libp2p.transport.quic.transport import (
    QuicTransport,
)


@pytest.mark.asyncio
async def test_quic_handshake():
    """Test QUIC handshake between client and server."""
    # Create server transport
    server_transport = QuicTransport(host="127.0.0.1", port=0)
    await server_transport.listen()

    # Create client transport
    client_transport = QuicTransport(host="127.0.0.1", port=0)

    # Create peer info for server
    server_peer_id = ID("QmTestServer")
    server_addr = f"/ip4/127.0.0.1/quic/{server_transport.port}"
    server_peer_info = PeerInfo(server_peer_id, [server_addr])

    # Dial server from client
    protocol, peer_info = await client_transport.dial(server_peer_info)

    # Verify connection was established
    assert protocol.connection is not None
    assert protocol.connection.is_connected()

    # Clean up
    await client_transport.close()
    await server_transport.close()


@pytest.mark.asyncio
async def test_quic_data_transfer():
    """Test data transfer over QUIC connection."""
    # Create server transport
    server_transport = QuicTransport(host="127.0.0.1", port=0)
    await server_transport.listen()

    # Create client transport
    client_transport = QuicTransport(host="127.0.0.1", port=0)

    # Create peer info for server
    server_peer_id = ID("QmTestServer")
    server_addr = f"/ip4/127.0.0.1/quic/{server_transport.port}"
    server_peer_info = PeerInfo(server_peer_id, [server_addr])

    # Dial server from client
    protocol, peer_info = await client_transport.dial(server_peer_info)

    # Create a stream and send data
    stream_id = protocol.connection.get_next_available_stream_id()
    test_data = b"Hello, QUIC!"
    await protocol.connection.send_stream_data(stream_id, test_data, end_stream=True)

    # Wait for data to be received
    received_data = await asyncio.get_event_loop().run_in_executor(
        None, lambda: protocol.connection.receive_stream_data(stream_id)
    )

    assert received_data == test_data

    # Clean up
    await client_transport.close()
    await server_transport.close()


@pytest.mark.asyncio
async def test_quic_error_handling():
    """Test error handling in QUIC transport."""
    # Create client transport
    client_transport = QuicTransport(host="127.0.0.1", port=0)

    # Test invalid peer info
    invalid_peer_id = ID("QmInvalidPeer")
    invalid_addr = "/ip4/127.0.0.1/quic/99999"  # Invalid port
    invalid_peer_info = PeerInfo(invalid_peer_id, [invalid_addr])

    with pytest.raises(TransportError):
        await client_transport.dial(invalid_peer_info)

    # Test connection timeout
    server_transport = QuicTransport(host="127.0.0.1", port=0)
    await server_transport.listen()

    # Define server_peer_info for timeout test
    server_peer_id = ID("QmTestServer")
    server_addr = f"/ip4/127.0.0.1/quic/{server_transport.port}"
    server_peer_info = PeerInfo(server_peer_id, [server_addr])

    # Try to connect with short timeout
    with pytest.raises(TransportError):
        await client_transport.dial(server_peer_info)

    # Clean up
    await client_transport.close()
    await server_transport.close()


@pytest.mark.asyncio
async def test_quic_multiple_streams():
    """Test handling multiple streams over a single QUIC connection."""
    # Create server transport
    server_transport = QuicTransport(host="127.0.0.1", port=0)
    await server_transport.listen()

    # Create client transport
    client_transport = QuicTransport(host="127.0.0.1", port=0)

    # Create peer info for server
    server_peer_id = ID("QmTestServer")
    server_addr = f"/ip4/127.0.0.1/quic/{server_transport.port}"
    server_peer_info = PeerInfo(server_peer_id, [server_addr])

    # Dial server from client
    protocol, peer_info = await client_transport.dial(server_peer_info)

    # Create multiple streams and send data
    streams_data = [
        (b"Stream 1 data", True),
        (b"Stream 2 data", False),
        (b"Stream 3 data", True),
    ]

    for data, end_stream in streams_data:
        stream_id = protocol.connection.get_next_available_stream_id()
        await protocol.connection.send_stream_data(
            stream_id, data, end_stream=end_stream
        )

        # Verify data was sent
        assert protocol.connection.stream_was_sent(stream_id)

    # Clean up
    await client_transport.close()
    await server_transport.close()


@pytest.mark.asyncio
async def test_quic_connection_resumption():
    """Test QUIC connection resumption using session tickets."""
    # Create server transport
    server_transport = QuicTransport(host="127.0.0.1", port=0)
    await server_transport.listen()

    # Create client transport
    client_transport = QuicTransport(host="127.0.0.1", port=0)

    # Create peer info for server
    server_peer_id = ID("QmTestServer")
    server_addr = f"/ip4/127.0.0.1/quic/{server_transport.port}"
    server_peer_info = PeerInfo(server_peer_id, [server_addr])

    # First connection
    protocol1, peer_info1 = await client_transport.dial(server_peer_info)
    await protocol1.connection.close()

    # Second connection (should use session ticket)
    protocol2, peer_info2 = await client_transport.dial(server_peer_info)

    # Verify second connection is using session resumption
    assert protocol2.connection.tls.session_resumed

    # Clean up
    await client_transport.close()
    await server_transport.close()
