from abc import ABC, abstractmethod
from typing import Dict, Tuple

from libp2p.typing import StreamHandlerFn, TProtocol

from .multiselect_communicator_interface import IMultiselectCommunicator


class IMultiselectMuxer(ABC):
    """
    Multiselect module that is responsible for responding to
    a multiselect client and deciding on
    a specific protocol and handler pair to use for communication
    """

    handlers: Dict[TProtocol, StreamHandlerFn]

    @abstractmethod
    def add_handler(self, protocol: TProtocol, handler: StreamHandlerFn) -> None:
        """
        Store the handler with the given protocol
        :param protocol: protocol name
        :param handler: handler function
        """

    @abstractmethod
    async def negotiate(
        self, communicator: IMultiselectCommunicator
    ) -> Tuple[TProtocol, StreamHandlerFn]:
        """
        Negotiate performs protocol selection
        :param stream: stream to negotiate on
        :return: selected protocol name, handler function
        :raise Exception: negotiation failed exception
        """
