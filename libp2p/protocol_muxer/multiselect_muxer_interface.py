from abc import (
    ABC,
    abstractmethod,
)

from libp2p.abc import (
    IMultiselectCommunicator,
)
from libp2p.custom_types import (
    StreamHandlerFn,
    TProtocol,
)


class IMultiselectMuxer(ABC):
    """
    Multiselect module that is responsible for responding to a multiselect
    client and deciding on a specific protocol and handler pair to use for
    communication.
    """

    handlers: dict[TProtocol, StreamHandlerFn]

    @abstractmethod
    def add_handler(self, protocol: TProtocol, handler: StreamHandlerFn) -> None:
        """
        Store the handler with the given protocol.

        :param protocol: protocol name
        :param handler: handler function
        """

    def get_protocols(self) -> tuple[TProtocol, ...]:
        return tuple(self.handlers.keys())

    @abstractmethod
    async def negotiate(
        self, communicator: IMultiselectCommunicator
    ) -> tuple[TProtocol, StreamHandlerFn]:
        """
        Negotiate performs protocol selection.

        :param stream: stream to negotiate on
        :return: selected protocol name, handler function
        :raise Exception: negotiation failed exception
        """
