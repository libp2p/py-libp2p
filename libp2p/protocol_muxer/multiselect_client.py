from collections.abc import (
    Sequence,
)

import trio

from libp2p.abc import (
    IMultiselectClient,
    IMultiselectCommunicator,
)
from libp2p.custom_types import (
    TProtocol,
)

from .exceptions import (
    MultiselectClientError,
    MultiselectCommunicatorError,
)

MULTISELECT_PROTOCOL_ID = "/multistream/1.0.0"
PROTOCOL_NOT_FOUND_MSG = "na"
DEFAULT_NEGOTIATE_TIMEOUT = 5


class MultiselectClient(IMultiselectClient):
    """
    Client for communicating with receiver's multiselect module in order to
    select a protocol id to communicate over.
    """

    async def handshake(self, communicator: IMultiselectCommunicator) -> None:
        """
        Ensure that the client and multiselect are both using the same
        multiselect protocol.

        :param communicator: communicator to use to communicate with counterparty
        :raise MultiselectClientError: raised when handshake failed
        """
        try:
            await communicator.write(MULTISELECT_PROTOCOL_ID)
        except MultiselectCommunicatorError as error:
            raise MultiselectClientError() from error

        try:
            handshake_contents = await communicator.read()

        except MultiselectCommunicatorError as error:
            raise MultiselectClientError() from error

        if not is_valid_handshake(handshake_contents):
            raise MultiselectClientError("multiselect protocol ID mismatch")

    async def select_one_of(
        self,
        protocols: Sequence[TProtocol],
        communicator: IMultiselectCommunicator,
        negotitate_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
    ) -> TProtocol:
        """
        For each protocol, send message to multiselect selecting protocol and
        fail if multiselect does not return same protocol. Returns first
        protocol that multiselect agrees on (i.e. that multiselect selects)

        :param protocol: protocol to select
        :param communicator: communicator to use to communicate with counterparty
        :param negotiate_timeout: timeout for negotiation
        :return: selected protocol
        :raise MultiselectClientError: raised when protocol negotiation failed
        """
        try:
            with trio.fail_after(negotitate_timeout):
                await self.handshake(communicator)

                for protocol in protocols:
                    try:
                        selected_protocol = await self.try_select(
                            communicator, protocol
                        )
                        return selected_protocol
                    except MultiselectClientError:
                        pass

                raise MultiselectClientError("protocols not supported")
        except trio.TooSlowError:
            raise MultiselectClientError("response timed out")

    async def query_multistream_command(
        self,
        communicator: IMultiselectCommunicator,
        command: str,
        response_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
    ) -> list[str]:
        """
        Send a multistream-select command over the given communicator and return
        parsed response.

        :param communicator: communicator to use to communicate with counterparty
        :param command: supported multistream-select command(e.g., ls)
        :param negotiate_timeout: timeout for negotiation
        :raise MultiselectClientError: If the communicator fails to process data.
        :return: list of strings representing the response from peer.
        """
        try:
            with trio.fail_after(response_timeout):
                await self.handshake(communicator)

                if command == "ls":
                    try:
                        await communicator.write("ls")
                    except MultiselectCommunicatorError as error:
                        raise MultiselectClientError() from error
                else:
                    raise ValueError("Command not supported")

                try:
                    response = await communicator.read()
                    response_list = response.strip().splitlines()

                except MultiselectCommunicatorError as error:
                    raise MultiselectClientError() from error

                return response_list
        except trio.TooSlowError:
            raise MultiselectClientError("command response timed out")

    async def try_select(
        self, communicator: IMultiselectCommunicator, protocol: TProtocol
    ) -> TProtocol:
        """
        Try to select the given protocol or raise exception if fails.

        :param communicator: communicator to use to communicate with counterparty
        :param protocol: protocol to select
        :raise MultiselectClientError: raised when protocol negotiation failed
        :return: selected protocol
        """
        try:
            await communicator.write(protocol)
        except MultiselectCommunicatorError as error:
            raise MultiselectClientError() from error

        try:
            response = await communicator.read()

        except MultiselectCommunicatorError as error:
            raise MultiselectClientError() from error

        if response == protocol:
            return protocol
        if response == PROTOCOL_NOT_FOUND_MSG:
            raise MultiselectClientError("protocol not supported")
        raise MultiselectClientError(f"unrecognized response: {response}")


def is_valid_handshake(handshake_contents: str) -> bool:
    """
    Determine if handshake is valid and should be confirmed.

    :param handshake_contents: contents of handshake message
    :return: true if handshake is complete, false otherwise
    """
    return handshake_contents == MULTISELECT_PROTOCOL_ID
