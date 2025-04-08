import pytest
import trio
from trio.testing import (
    memory_stream_pair,
)

from libp2p.crypto.ed25519 import (
    create_new_key_pair,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.security.insecure.transport import (
    InsecureTransport,
)
from libp2p.stream_muxer.yamux.yamux import (
    MuxedStreamError,
    Yamux,
    YamuxStream,
)


class TrioStreamAdapter:
    def __init__(self, send_stream, receive_stream):
        self.send_stream = send_stream
        self.receive_stream = receive_stream

    async def write(self, data):
        print(f"Writing {len(data)} bytes")
        with trio.move_on_after(2):
            await self.send_stream.send_all(data)

    async def read(self, n=-1):
        if n == -1:
            raise ValueError("Reading unbounded not supported")
        print(f"Attempting to read {n} bytes")
        with trio.move_on_after(2):
            data = await self.receive_stream.receive_some(n)
            print(f"Read {len(data)} bytes")
            return data

    async def close(self):
        print("Closing stream")


@pytest.fixture
def key_pair():
    return create_new_key_pair()


@pytest.fixture
def peer_id(key_pair):
    return ID.from_pubkey(key_pair.public_key)


@pytest.fixture
async def secure_conn_pair(key_pair, peer_id):
    print("Setting up secure_conn_pair")
    client_send, server_receive = memory_stream_pair()
    server_send, client_receive = memory_stream_pair()

    client_rw = TrioStreamAdapter(client_send, client_receive)
    server_rw = TrioStreamAdapter(server_send, server_receive)

    insecure_transport = InsecureTransport(key_pair)

    async def run_outbound(nursery_results):
        with trio.move_on_after(5):
            client_conn = await insecure_transport.secure_outbound(client_rw, peer_id)
            print("Outbound handshake complete")
            nursery_results["client"] = client_conn

    async def run_inbound(nursery_results):
        with trio.move_on_after(5):
            server_conn = await insecure_transport.secure_inbound(server_rw)
            print("Inbound handshake complete")
            nursery_results["server"] = server_conn

    nursery_results = {}
    async with trio.open_nursery() as nursery:
        nursery.start_soon(run_outbound, nursery_results)
        nursery.start_soon(run_inbound, nursery_results)
        await trio.sleep(0.1)  # Give tasks a chance to finish

    client_conn = nursery_results.get("client")
    server_conn = nursery_results.get("server")

    if client_conn is None or server_conn is None:
        raise RuntimeError("Handshake failed: client_conn or server_conn is None")

    print("secure_conn_pair setup complete")
    return client_conn, server_conn


@pytest.fixture
async def yamux_pair(secure_conn_pair, peer_id):
    print("Setting up yamux_pair")
    client_conn, server_conn = secure_conn_pair
    client_yamux = Yamux(client_conn, peer_id, is_initiator=True)
    server_yamux = Yamux(server_conn, peer_id, is_initiator=False)
    async with trio.open_nursery() as nursery:
        with trio.move_on_after(5):
            nursery.start_soon(client_yamux.start)
            nursery.start_soon(server_yamux.start)
            await trio.sleep(0.1)
            print("yamux_pair started")
        yield client_yamux, server_yamux
    print("yamux_pair cleanup")


@pytest.mark.trio
async def test_yamux_stream_creation(yamux_pair):
    print("Starting test_yamux_stream_creation")
    client_yamux, server_yamux = yamux_pair
    assert client_yamux.is_initiator
    assert not server_yamux.is_initiator
    with trio.move_on_after(5):
        stream = await client_yamux.open_stream()
        print("Stream opened")
        assert isinstance(stream, YamuxStream)
        assert stream.stream_id % 2 == 1
    print("test_yamux_stream_creation complete")


@pytest.mark.trio
async def test_yamux_accept_stream(yamux_pair):
    print("Starting test_yamux_accept_stream")
    client_yamux, server_yamux = yamux_pair
    client_stream = await client_yamux.open_stream()
    server_stream = await server_yamux.accept_stream()
    assert server_stream.stream_id == client_stream.stream_id
    assert isinstance(server_stream, YamuxStream)
    print("test_yamux_accept_stream complete")


@pytest.mark.trio
async def test_yamux_data_transfer(yamux_pair):
    print("Starting test_yamux_data_transfer")
    client_yamux, server_yamux = yamux_pair
    client_stream = await client_yamux.open_stream()
    server_stream = await server_yamux.accept_stream()
    test_data = b"hello yamux"
    await client_stream.write(test_data)
    received = await server_stream.read(len(test_data))
    assert received == test_data
    reply_data = b"hi back"
    await server_stream.write(reply_data)
    received = await client_stream.read(len(reply_data))
    assert received == reply_data
    print("test_yamux_data_transfer complete")


@pytest.mark.trio
async def test_yamux_stream_close(yamux_pair):
    print("Starting test_yamux_stream_close")
    client_yamux, server_yamux = yamux_pair
    client_stream = await client_yamux.open_stream()
    server_stream = await server_yamux.accept_stream()
    await client_stream.close()
    received = await server_stream.read()
    assert received == b""
    assert client_stream.closed
    with pytest.raises(MuxedStreamError):
        await client_stream.write(b"test")
    print("test_yamux_stream_close complete")


@pytest.mark.trio
async def test_yamux_stream_reset(yamux_pair):
    print("Starting test_yamux_stream_reset")
    client_yamux, server_yamux = yamux_pair
    client_stream = await client_yamux.open_stream()
    server_stream = await server_yamux.accept_stream()
    await client_stream.reset()
    data = await server_stream.read()
    assert data == b"", "Expected empty read after reset"
    print("test_yamux_stream_reset complete")


@pytest.mark.trio
async def test_yamux_connection_close(yamux_pair):
    print("Starting test_yamux_connection_close")
    client_yamux, server_yamux = yamux_pair
    await client_yamux.open_stream()
    await server_yamux.accept_stream()
    await client_yamux.close()
    print("Closing stream")
    await trio.sleep(0.2)
    assert client_yamux.is_closed
    assert server_yamux.event_shutting_down.is_set()
    print("test_yamux_connection_close complete")
