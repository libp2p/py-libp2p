import pytest
import trio

from libp2p.abc import (
    IMultiselectCommunicator,
)
from libp2p.custom_types import TProtocol
from libp2p.protocol_muxer.exceptions import (
    MultiselectClientError,
    MultiselectError,
)
from libp2p.protocol_muxer.multiselect import Multiselect
from libp2p.protocol_muxer.multiselect_client import MultiselectClient


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
async def test_select_one_of_timeout():
    ECHO = TProtocol("/echo/1.0.0")
    communicator = DummyMultiselectCommunicator()

    client = MultiselectClient()

    with pytest.raises(MultiselectClientError, match="response timed out"):
        await client.select_one_of([ECHO], communicator, 2)


@pytest.mark.trio
async def test_query_multistream_command_timeout():
    communicator = DummyMultiselectCommunicator()
    client = MultiselectClient()

    with pytest.raises(MultiselectClientError, match="response timed out"):
        await client.query_multistream_command(communicator, "ls", 2)


@pytest.mark.trio
async def test_negotiate_timeout():
    communicator = DummyMultiselectCommunicator()
    server = Multiselect()

    with pytest.raises(MultiselectError, match="handshake read timeout"):
        await server.negotiate(communicator, 2)
