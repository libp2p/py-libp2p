from .multiselect_communicator_interface import IMultiselectCommunicator

class MultiselectCommunicator(IMultiselectCommunicator):

    def __init__(self, stream):
        self.stream = stream

    async def write(msg_str):
        await stream.write(msg_str.encode())

    async def read_stream_until_eof():
        read_string = (await stream.read()).decode()
        return read_string
