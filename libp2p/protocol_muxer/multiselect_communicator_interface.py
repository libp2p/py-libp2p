from abc import ABC, abstractmethod


class IMultiselectCommunicator(ABC):
    """
    Communicator helper class that ensures both the client
    and multistream module will follow the same multistream protocol,
    which is necessary for them to work
    """

    @abstractmethod
    def write(self, msg_str):
        """
        Write message to stream
        :param msg_str: message to write
        """

    @abstractmethod
    def read_stream_until_eof(self):
        """
        Reads message from stream until EOF
        """
