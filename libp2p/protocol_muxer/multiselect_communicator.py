from .multiselect_communicator_interface import IMultiselectCommunicator


class MultiselectCommunicator(IMultiselectCommunicator):
    """
    Communicator helper class that ensures both the client
    and multistream module will follow the same multistream protocol,
    which is necessary for them to work
    """

    def __init__(self, stream):
        self.stream = stream

    async def write(self, msg_str):
        """
        Write message to stream
        :param msg_str: message to write
        """
        await self.stream.write(msg_str.encode())

    async def read_stream_until_eof(self):
        """
        Reads message from stream until EOF
        """
        read_str = (await self.stream.read()).decode()
        return read_str
