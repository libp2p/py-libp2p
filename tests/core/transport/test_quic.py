import trio
import pytest
from libp2p.core.quic import QuicProtocol, QuicConfiguration


@pytest.mark.trio
async def test_quic_handshake():
    configuration = QuicConfiguration(is_client=True)
    protocol = QuicProtocol("127.0.0.1", 4433, configuration)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(protocol.run)
        # Add additional assertions or conditions as needed
