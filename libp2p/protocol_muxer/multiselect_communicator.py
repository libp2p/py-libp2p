from .multiselect_communicator_interface import IMultiselectCommunicator


class MultiselectCommunicator(IMultiselectCommunicator):
    """
    Communicator helper class that ensures both the client
    and multistream module will follow the same multistream protocol,
    which is necessary for them to work
    """

    def __init__(self, reader_writer):
        """
        MultistreamCommunicator expects a reader_writer object that has
        an async read and an async write function (this could be a stream,
        raw connection, or other object implementing those functions)
        """
        self.reader_writer = reader_writer

    async def write(self, msg_str):
        """
        Write message to reader_writer
        :param msg_str: message to write
        """
        await self.reader_writer.write(msg_str.encode())

    async def read_stream_until_eof(self):
        """
        Reads message from reader_writer until EOF
        """
        read_str = (await self.reader_writer.read()).decode()
        return read_str
