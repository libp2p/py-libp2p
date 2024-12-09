
import pytest
from libp2p_quic_transport.quic_transport import QuicTransport

@pytest.mark.asyncio
async def test_quic_transport_dial():
    transport = QuicTransport(local_peer="test_peer")
    # Assuming a test QUIC server is running at 127.0.0.1:4433
    conn = await transport.dial("test_peer_id", "/ip4/127.0.0.1/tcp/4433")
    assert conn is not None

@pytest.mark.asyncio
async def test_quic_transport_listen():
    transport = QuicTransport(local_peer="test_peer")
    server = await transport.listen("/ip4/127.0.0.1/tcp/4433")
    assert server is not None
