from collections import deque

import pytest
import trio

from libp2p.abc import IMultiselectCommunicator, INetStream
from libp2p.custom_types import TProtocol
from libp2p.protocol_muxer.exceptions import (
    MultiselectClientError,
    MultiselectError,
)
from libp2p.protocol_muxer.multiselect import Multiselect
from libp2p.protocol_muxer.multiselect_client import MultiselectClient


async def dummy_handler(stream: INetStream) -> None:
    pass


class DummyMultiselectCommunicator(IMultiselectCommunicator):
    """
    Dummy MultiSelectCommunicator to test out negotiate timmeout.
    """

    def __init__(self) -> None:
        return

    async def write(self, msg_str: str) -> None:
        """Goes into infinite loop when .write is called"""
        await trio.sleep_forever()

    async def read(self) -> str:
        """Returns a dummy read"""
        return "dummy_read"


@pytest.mark.trio
async def test_select_one_of_timeout() -> None:
    ECHO = TProtocol("/echo/1.0.0")
    communicator = DummyMultiselectCommunicator()

    client = MultiselectClient()

    with pytest.raises(MultiselectClientError, match="response timed out"):
        await client.select_one_of([ECHO], communicator, 2)


@pytest.mark.trio
async def test_query_multistream_command_timeout() -> None:
    communicator = DummyMultiselectCommunicator()
    client = MultiselectClient()

    with pytest.raises(MultiselectClientError, match="response timed out"):
        await client.query_multistream_command(communicator, "ls", 2)


@pytest.mark.trio
async def test_negotiate_timeout() -> None:
    communicator = DummyMultiselectCommunicator()
    server = Multiselect()

    with pytest.raises(MultiselectError, match="handshake read timeout"):
        await server.negotiate(communicator, 2)


class HandshakeThenHangCommunicator(IMultiselectCommunicator):
    handshaked: bool

    def __init__(self) -> None:
        self.handshaked = False

    async def write(self, msg_str: str) -> None:
        if msg_str == "/multistream/1.0.0":
            self.handshaked = True
        return

    async def read(self) -> str:
        if not self.handshaked:
            return "/multistream/1.0.0"
        # After handshake, hang on read.
        await trio.sleep_forever()
        # Should not be reached.
        return ""


@pytest.mark.trio
async def test_negotiate_timeout_post_handshake() -> None:
    communicator = HandshakeThenHangCommunicator()
    server = Multiselect()
    with pytest.raises(MultiselectError, match="handshake read timeout"):
        await server.negotiate(communicator, 1)


class MockCommunicator(IMultiselectCommunicator):
    def __init__(self, commands_to_read: list[str]):
        self.read_queue = deque(commands_to_read)
        self.written_data: list[str] = []

    async def write(self, msg_str: str) -> None:
        self.written_data.append(msg_str)

    async def read(self) -> str:
        if not self.read_queue:
            raise EOFError
        return self.read_queue.popleft()


@pytest.mark.trio
async def test_negotiate_empty_string_command() -> None:
    # server receives an empty string, which means client wants `None` protocol.
    server = Multiselect({None: dummy_handler})
    # Handshake, then empty command
    communicator = MockCommunicator(["/multistream/1.0.0", ""])
    protocol, handler = await server.negotiate(communicator)
    assert protocol is None
    assert handler == dummy_handler
    # Check that server sent back handshake and the protocol confirmation (empty string)
    assert communicator.written_data == ["/multistream/1.0.0", ""]


@pytest.mark.trio
async def test_negotiate_with_none_handler() -> None:
    # server has None handler, client sends "" to select it.
    server = Multiselect({None: dummy_handler, TProtocol("/proto1"): dummy_handler})
    # Handshake, then empty command
    communicator = MockCommunicator(["/multistream/1.0.0", ""])
    protocol, handler = await server.negotiate(communicator)
    assert protocol is None
    assert handler == dummy_handler
    # Check written data: handshake, protocol confirmation
    assert communicator.written_data == ["/multistream/1.0.0", ""]


@pytest.mark.trio
async def test_negotiate_with_none_handler_ls() -> None:
    # server has None handler, client sends "ls" then empty string.
    server = Multiselect({None: dummy_handler, TProtocol("/proto1"): dummy_handler})
    # Handshake, ls, empty command
    communicator = MockCommunicator(["/multistream/1.0.0", "ls", ""])
    protocol, handler = await server.negotiate(communicator)
    assert protocol is None
    assert handler == dummy_handler
    # Check written data: handshake, ls response, protocol confirmation
    assert communicator.written_data[0] == "/multistream/1.0.0"
    assert "/proto1" in communicator.written_data[1]
    # Note: `ls` should not list the `None` protocol.
    assert "None" not in communicator.written_data[1]
    assert "\n\n" not in communicator.written_data[1]
    assert communicator.written_data[2] == ""
