import trio

from libp2p.abc import (
    IMultiselectCommunicator,
    IMultiselectMuxer,
)
from libp2p.custom_types import (
    StreamHandlerFn,
    TProtocol,
)

from .exceptions import (
    MultiselectCommunicatorError,
    MultiselectError,
)

MULTISELECT_PROTOCOL_ID = "/multistream/1.0.0"
PROTOCOL_NOT_FOUND_MSG = "na"
DEFAULT_NEGOTIATE_TIMEOUT = 5


class Multiselect(IMultiselectMuxer):
    """
    Multiselect module that is responsible for responding to a multiselect
    client and deciding on a specific protocol and handler pair to use for
    communication.
    """

    handlers: dict[TProtocol | None, StreamHandlerFn | None]

    def __init__(
        self,
        default_handlers: None
        | (dict[TProtocol | None, StreamHandlerFn | None]) = None,
    ) -> None:
        if not default_handlers:
            default_handlers = {}
        self.handlers = default_handlers

    def add_handler(
        self, protocol: TProtocol | None, handler: StreamHandlerFn | None
    ) -> None:
        """
        Store the handler with the given protocol.

        :param protocol: protocol name
        :param handler: handler function
        """
        self.handlers[protocol] = handler

    # FIXME: Make TProtocol Optional[TProtocol] to keep types consistent
    async def negotiate(
        self,
        communicator: IMultiselectCommunicator,
        negotiate_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
    ) -> tuple[TProtocol, StreamHandlerFn | None]:
        """
        Negotiate performs protocol selection.

        :param stream: stream to negotiate on
        :param negotiate_timeout: timeout for negotiation
        :return: selected protocol name, handler function
        :raise MultiselectError: raised when negotiation failed
        """
        try:
            with trio.fail_after(negotiate_timeout):
                await self.handshake(communicator)

                while True:
                    try:
                        command = await communicator.read()
                    except MultiselectCommunicatorError as error:
                        raise MultiselectError() from error

                    if command == "ls":
                        supported_protocols = [
                            p for p in self.handlers.keys() if p is not None
                        ]
                        response = "\n".join(supported_protocols) + "\n"

                        try:
                            await communicator.write(response)
                        except MultiselectCommunicatorError as error:
                            raise MultiselectError() from error

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

                raise MultiselectError("Negotiation failed: no matching protocol")
        except trio.TooSlowError:
            raise MultiselectError("handshake read timeout")

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
