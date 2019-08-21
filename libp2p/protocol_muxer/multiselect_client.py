from typing import Sequence

from libp2p.typing import TProtocol

from .exceptions import MultiselectClientError
from .multiselect_client_interface import IMultiselectClient
from .multiselect_communicator_interface import IMultiselectCommunicator

MULTISELECT_PROTOCOL_ID = "/multistream/1.0.0"
PROTOCOL_NOT_FOUND_MSG = "na"


class MultiselectClient(IMultiselectClient):
    """
    Client for communicating with receiver's multiselect
    module in order to select a protocol id to communicate over
    """

    async def handshake(self, communicator: IMultiselectCommunicator) -> None:
        """
        Ensure that the client and multiselect
        are both using the same multiselect protocol
        :param stream: stream to communicate with multiselect over
        :raise Exception: multiselect protocol ID mismatch
        """

        # TODO: Use format used by go repo for messages

        # Send our MULTISELECT_PROTOCOL_ID to counterparty
        await communicator.write(MULTISELECT_PROTOCOL_ID)

        # Read in the protocol ID from other party
        handshake_contents = await communicator.read()

        # Confirm that the protocols are the same
        if not validate_handshake(handshake_contents):
            raise MultiselectClientError("multiselect protocol ID mismatch")

        # Handshake succeeded if this point is reached

    async def select_protocol_or_fail(
        self, protocol: TProtocol, communicator: IMultiselectCommunicator
    ) -> TProtocol:
        """
        Send message to multiselect selecting protocol
        and fail if multiselect does not return same protocol
        :param protocol: protocol to select
        :param stream: stream to communicate with multiselect over
        :return: selected protocol
        """
        # Perform handshake to ensure multiselect protocol IDs match
        await self.handshake(communicator)

        # Try to select the given protocol
        selected_protocol = await self.try_select(communicator, protocol)

        return selected_protocol

    async def select_one_of(
        self, protocols: Sequence[TProtocol], communicator: IMultiselectCommunicator
    ) -> TProtocol:
        """
        For each protocol, send message to multiselect selecting protocol
        and fail if multiselect does not return same protocol. Returns first
        protocol that multiselect agrees on (i.e. that multiselect selects)
        :param protocol: protocol to select
        :param stream: stream to communicate with multiselect over
        :return: selected protocol
        """
        # Perform handshake to ensure multiselect protocol IDs match
        await self.handshake(communicator)

        # For each protocol, attempt to select that protocol
        # and return the first protocol selected
        for protocol in protocols:
            try:
                selected_protocol = await self.try_select(communicator, protocol)
                return selected_protocol
            except MultiselectClientError:
                pass

        # No protocols were found, so return no protocols supported error
        raise MultiselectClientError("protocols not supported")

    async def try_select(
        self, communicator: IMultiselectCommunicator, protocol: TProtocol
    ) -> TProtocol:
        """
        Try to select the given protocol or raise exception if fails
        :param communicator: communicator to use to communicate with counterparty
        :param protocol: protocol to select
        :raise Exception: error in protocol selection
        :return: selected protocol
        """

        # Tell counterparty we want to use protocol
        await communicator.write(protocol)

        # Get what counterparty says in response
        response = await communicator.read()

        # Return protocol if response is equal to protocol or raise error
        if response == protocol:
            return protocol
        if response == PROTOCOL_NOT_FOUND_MSG:
            raise MultiselectClientError("protocol not supported")
        raise MultiselectClientError("unrecognized response: " + response)


def validate_handshake(handshake_contents: str) -> bool:
    """
    Determine if handshake is valid and should be confirmed
    :param handshake_contents: contents of handshake message
    :return: true if handshake is complete, false otherwise
    """

    # TODO: Modify this when format used by go repo for messages
    # is added
    return handshake_contents == MULTISELECT_PROTOCOL_ID
