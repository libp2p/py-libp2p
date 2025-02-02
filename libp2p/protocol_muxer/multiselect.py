from libp2p.custom_types import (
    StreamHandlerFn,
    TProtocol,
)

from .exceptions import (
    MultiselectCommunicatorError,
    MultiselectError,
)
from .multiselect_communicator_interface import (
    IMultiselectCommunicator,
)
from .multiselect_muxer_interface import (
    IMultiselectMuxer,
)

MULTISELECT_PROTOCOL_ID = "/multistream/1.0.0"
PROTOCOL_NOT_FOUND_MSG = "na"


class Multiselect(IMultiselectMuxer):
    """
    Multiselect module that is responsible for responding to a multiselect
    client and deciding on a specific protocol and handler pair to use for
    communication.
    """

    handlers: dict[TProtocol, StreamHandlerFn]

    def __init__(
        self, default_handlers: dict[TProtocol, StreamHandlerFn] = None
    ) -> None:
        if not default_handlers:
            default_handlers = {}
        self.handlers = default_handlers

    def add_handler(self, protocol: TProtocol, handler: StreamHandlerFn) -> None:
        """
        Store the handler with the given protocol.

        :param protocol: protocol name
        :param handler: handler function
        """
        self.handlers[protocol] = handler

    async def negotiate(
        self, communicator: IMultiselectCommunicator
    ) -> tuple[TProtocol, StreamHandlerFn]:
        """
        Negotiate performs protocol selection.

        :param stream: stream to negotiate on
        :return: selected protocol name, handler function
        :raise MultiselectError: raised when negotiation failed
        """
        await self.handshake(communicator)

        while True:
            try:
                command = await communicator.read()
            except MultiselectCommunicatorError as error:
                raise MultiselectError() from error

            if command == "ls":
                # TODO: handle ls command
                pass
            else:
                protocol = TProtocol(command)
                if protocol in self.handlers:
                    try:
                        await communicator.write(protocol)
                    except MultiselectCommunicatorError as error:
                        raise MultiselectError() from error

                    return protocol, self.handlers[protocol]
                try:
                    await communicator.write(PROTOCOL_NOT_FOUND_MSG)
                except MultiselectCommunicatorError as error:
                    raise MultiselectError() from error

    async def handshake(self, communicator: IMultiselectCommunicator) -> None:
        """
        Perform handshake to agree on multiselect protocol.

        :param communicator: communicator to use
        :raise MultiselectError: raised when handshake failed
        """
        try:
            await communicator.write(MULTISELECT_PROTOCOL_ID)
        except MultiselectCommunicatorError as error:
            raise MultiselectError() from error

        try:
            handshake_contents = await communicator.read()
        except MultiselectCommunicatorError as error:
            raise MultiselectError() from error

        if not is_valid_handshake(handshake_contents):
            raise MultiselectError(
                "multiselect protocol ID mismatch: "
                f"received handshake_contents={handshake_contents}"
            )


def is_valid_handshake(handshake_contents: str) -> bool:
    """
    Determine if handshake is valid and should be confirmed.

    :param handshake_contents: contents of handshake message
    :return: true if handshake is complete, false otherwise
    """
    return handshake_contents == MULTISELECT_PROTOCOL_ID
