from libp2p.exceptions import ParseError
from libp2p.io.abc import ReadWriteCloser
from libp2p.io.exceptions import IOException
from libp2p.utils import encode_delim, read_delim

from .exceptions import MultiselectCommunicatorError
from .multiselect_communicator_interface import IMultiselectCommunicator


class MultiselectCommunicator(IMultiselectCommunicator):
    read_writer: ReadWriteCloser

    def __init__(self, read_writer: ReadWriteCloser) -> None:
        self.read_writer = read_writer

    async def write(self, msg_str: str) -> None:
        msg_bytes = encode_delim(msg_str.encode())
        try:
            await self.read_writer.write(msg_bytes)
        except IOException:
            raise MultiselectCommunicatorError(
                "fail to write to multiselect communicator"
            )

    async def read(self) -> str:
        try:
            data = await read_delim(self.read_writer)
        # `IOException` includes `IncompleteReadError` and `StreamError`
        except (ParseError, IOException, ValueError):
            raise MultiselectCommunicatorError(
                "fail to read from multiselect communicator"
            )
        return data.decode()
