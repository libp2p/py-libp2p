from libp2p.io.abc import ReadWriteCloser
from libp2p.utils import encode_delim, read_delim

from .multiselect_communicator_interface import IMultiselectCommunicator


class MultiselectCommunicator(IMultiselectCommunicator):
    read_writer: ReadWriteCloser

    def __init__(self, read_writer: ReadWriteCloser) -> None:
        self.read_writer = read_writer

    async def write(self, msg_str: str) -> None:
        msg_bytes = encode_delim(msg_str.encode())
        await self.read_writer.write(msg_bytes)

    async def read(self) -> str:
        data = await read_delim(self.read_writer)
        return data.decode()
