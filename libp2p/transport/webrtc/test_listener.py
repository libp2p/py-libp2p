import pytest
from multiaddr import (
    Multiaddr,
)

from libp2p.transport.webrtc.connection import (
    WebRTCRawConnection,
)
from libp2p.transport.webrtc.listener import (
    SIGNAL_PROTOCOL,
    WebRTCListener,
)


@pytest.mark.trio
async def test_listen_and_accept_direct_connection():
    listener = WebRTCListener()
    maddr = Multiaddr("/ip4/127.0.0.1/tcp/9999/webrtc-direct")
    await listener.listen(maddr)

    class DummyChannel:
        def __init__(self):
            self.label = "test"
            self._on_message = None
            self._on_open = None
            self.readyState = "open"

        def on(self, event):
            def decorator(fn):
                if event == "message":
                    self._on_message = fn
                elif event == "open":
                    self._on_open = fn
                return fn

            return decorator

        def send(self, data):
            pass

    dummy_channel = DummyChannel()

    # creating a WebRTCRawConnection and sending the listener's channel
    conn = WebRTCRawConnection(listener.peer_id, dummy_channel)
    await listener.conn_send_channel.send(conn)
    await listener.accept()

    # maddr = "/ip4/127.0.0.1/udp/9000/webrtc-direct/
    # certhash/uEiqfMpAA6QOH0DT7YC5ggjBBG-c3CqLqbhQ4ovz4q6NyY/
    # p2p/12D3KooWGiZiY9Vz2CCbbDkJATUrgZ6b6ov7f6AxZPkWR573V3Bx"
    # result = await listener.listen(maddr)
    # assert result is True
    # addrs = listener.get_addrs()
    # assert maddr in addrs
    # assert isinstance(addrs, tuple)
    # assert len(addrs) == 1

    # Accept the connection
    # accepted_conn = trio.move_on_after(1)

    # assert isinstance(accepted_conn, WebRTCRawConnection)
    # assert accepted_conn.peer_id == listener.peer_id
    # assert hasattr(accepted_conn, "channel")
    # assert accepted_conn.channel.label == "test"


class DummyNetwork:
    def __init__(self):
        self.listen_called_with = []
        self._peer_id = b"dummy_peer_id"

    async def listen(self, maddr):
        self.listen_called_with.append(maddr)
        return True

    def get_peer_id(self):
        return self._peer_id


class DummyHost:
    def __init__(self):
        self.stream_handlers = {}
        self._network = DummyNetwork()

    def set_stream_handler(self, protocol_id, handler):
        self.stream_handlers[protocol_id] = handler

    def get_network(self):
        return self._network

    def get_id(self):
        return self._network.get_peer_id()


@pytest.mark.trio
async def test_listen_signaled_registers_stream_handler():
    listener = WebRTCListener()
    dummy_host = DummyHost()
    listener.set_host(dummy_host)
    maddr = Multiaddr("/ip4/127.0.0.1/tcp/12345/ws/p2p-webrtc-star")
    result = await listener.listen_signaled(maddr)
    # Check that the stream handler was registered for the signal protocol
    assert SIGNAL_PROTOCOL in dummy_host.stream_handlers
    # Check that the network's listen was called with the correct multiaddr
    assert maddr in dummy_host.get_network().listen_called_with
    # Check that the listen_signaled returns True
    assert result is True
    # Check that the address is added to the listener's addrs
    assert maddr in listener.get_addrs()
