import trio
import pytest
from libp2p.transport.websocket.listener import WebsocketListener
from multiaddr import Multiaddr
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.custom_types import TProtocol
from trio_websocket import open_websocket_url
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.security.insecure.transport import InsecureTransport
from libp2p.stream_muxer.yamux.yamux import Yamux

PLAINTEXT_PROTOCOL_ID = "/plaintext/1.0.0"

def create_upgrader():
    """Helper function to create a transport upgrader"""
    key_pair = create_new_key_pair()
    return TransportUpgrader(
        secure_transports_by_protocol={
            TProtocol(PLAINTEXT_PROTOCOL_ID): InsecureTransport(key_pair)
        },
        muxer_transports_by_protocol={TProtocol("/yamux/1.0.0"): Yamux},
    )

def get_ws_maddr(port=0, secure=False):
    protocol = "wss" if secure else "ws"
    return Multiaddr(f"/ip4/127.0.0.1/tcp/{port}/{protocol}")

@pytest.mark.trio
async def test_ws_handler_data_flow():
    """
    Verify that the handler actually receives a wrapped connection and can read/write.
    """
    server_received = trio.Event()
    
    async def echo_handler(conn):
        data = await conn.read(1024)
        await conn.write(data)
        await conn.close()
        server_received.set()

    listener = WebsocketListener(handler=echo_handler, upgrader=create_upgrader())
    await listener.listen(get_ws_maddr(0))
    port = listener.get_addrs()[0].value_for_protocol("tcp")
    
    async with open_websocket_url(f"ws://127.0.0.1:{port}") as ws:
        await ws.send_message(b"ping")
        response = await ws.get_message()
        assert response == b"ping"

    await server_received.wait()
    await listener.close()