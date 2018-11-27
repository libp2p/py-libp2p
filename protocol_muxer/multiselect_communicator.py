from .multiselect_communicator_interface import IMultiselectCommunicator

class MultiselectCommunicator(IMultiselectCommunicator):

    def __init__(self, stream):
        self.stream = stream

    async def write(self, msg_str):
        await self.stream.write(msg_str.encode())

    async def read_stream_until_eof(self):
        read_str = (await self.stream.read()).decode()
        return read_str
