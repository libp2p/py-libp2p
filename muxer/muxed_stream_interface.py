from abc import ABC, abstractmethod
from datetime import time

class IMuxedStream(ABC):

    # TODO Reader
    # TODO Writer
    # TODO Closer

    @abstractmethod
    def reset(self):
        """
        closes both ends of the stream
        tells this remote side to hang up
        :return: error/exception
        """
        pass

    @abstractmethod
    def set_deadline(self, ttl):
        """
        set deadline for muxed stream
        :return: a new stream
        """
        pass
