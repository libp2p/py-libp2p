import ssl

import pytest
from multiaddr import (
    Multiaddr,
)
import trio

from libp2p.transport.quic.transport import (
    QuicTransport,
)


@pytest.mark.trio
async def test_quic_handshake():
    async def handler(protocol):
        # Dummy handler: just keep the protocol alive
        await trio.sleep_forever()

    transport1 = QuicTransport(host="127.0.0.1", port=0)
    transport2 = QuicTransport(host="127.0.0.1", port=0)

    ready = trio.Event()

    async def run_listener():
        await transport2.listen()  # Ensure the listener is started correctly
        ready.set()  # Signal that listener is ready

    async with trio.open_nursery() as nursery:
        nursery.start_soon(run_listener)
        await ready.wait()
        addr2 = transport2.get_addrs()[0]
        print("QUIC listener started at", addr2)
        conn = await transport1.dial(addr2)

        assert conn is not None
        # assert conn.connection is not None
        # assert conn.connection.is_connected()

        await transport1.close()
        await transport2.close()
        nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_quic_streams():
    async def handler(protocol):
        # Wait for streams and echo data back
        while True:
            for stream in protocol._streams.values():
                data = await stream.read()
                if data:
                    await stream.write(data)
            await trio.sleep(0.01)

    transport1 = QuicTransport(host="127.0.0.1", port=0)
    transport2 = QuicTransport(host="127.0.0.1", port=0)

    async with trio.open_nursery() as nursery:
        listener1 = transport1.create_listener(handler)
        listener2 = transport2.create_listener(handler)
        await listener1.listen(Multiaddr("/ip4/127.0.0.1/udp/0/quic"), nursery)
        await listener2.listen(Multiaddr("/ip4/127.0.0.1/udp/0/quic"), nursery)

        conn = await transport1.dial(listener2.get_addrs()[0])
        stream = await conn.open_stream()

        test_data = b"Hello QUIC!"
        await stream.write(test_data)
        received = await stream.read(len(test_data))
        assert received == test_data

        await transport1.close()
        await transport2.close()
        nursery.cancel_scope.cancel()


# In QuicTransport class
context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")
context.set_alpn_protocols(["h3"])  # Set ALPN to HTTP/3
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE
context.minimum_version = ssl.TLSVersion.TLSv1_3
