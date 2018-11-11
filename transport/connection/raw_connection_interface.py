from abc import ABC, abstractmethod

class IRawConnection(ABC):
    """
    A Raw Connection provides a Reader and a Writer
    open_connection should return such a connection
    """

    # @abstractmethod
    # async def open_connection(self):
    #     """
    #     opens a connection on ip and port
    #     :return: a raw connection
    #     """
    #     pass
