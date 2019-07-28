from abc import ABC, abstractmethod
from typing import (
    Any,
    Coroutine,
)


class INetStream(ABC):

    @abstractmethod
    def get_protocol(self) -> str:
        """
        :return: protocol id that stream runs on
        """

    @abstractmethod
    def set_protocol(self, protocol_id: str) -> bool:
        """
        :param protocol_id: protocol id that stream runs on
        :return: true if successful
        """

    @abstractmethod
    def read(self) -> Coroutine[Any, Any, bytes]:
        """
        reads from the underlying muxed_stream
        :return: bytes of input
        """

    @abstractmethod
    def write(self, data: bytes) -> Coroutine[Any, Any, int]:
        """
        write to the underlying muxed_stream
        :return: number of bytes written
        """

    @abstractmethod
    def close(self) -> Coroutine[Any, Any, bool]:
        """
        close the underlying muxed stream
        :return: true if successful
        """
