from aioquic.quic.configuration import QuicConfiguration
import pytest
import trio

from libp2p.transport.quic.quic import QuicProtocol


@pytest.mark.trio
async def test_quic_handshake():
    configuration = QuicConfiguration(is_client=True)
    protocol = QuicProtocol("127.0.0.1", 4433, configuration)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(protocol.run)
        await trio.sleep(1)  # Wait for the handshake to complete

    assert protocol._handshake_complete.is_set()