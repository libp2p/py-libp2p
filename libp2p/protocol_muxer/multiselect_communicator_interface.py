from abc import ABC, abstractmethod


class IMultiselectCommunicator(ABC):
    """
    Communicator helper class that ensures both the client
    and multistream module will follow the same multistream protocol,
    which is necessary for them to work
    """

    @abstractmethod
    async def write(self, msg_str: str) -> None:
        """
        Write message to stream
        :param msg_str: message to write
        """

    @abstractmethod
    async def read(self) -> str:
        """
        Reads message from stream until EOF
        """
