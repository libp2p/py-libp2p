from .multiselect_client_interface import IMultiselectClient
from .multiselect_communicator import MultiselectCommunicator


MULTISELECT_PROTOCOL_ID = "/multistream/1.0.0"
PROTOCOL_NOT_FOUND_MSG = "na"


class MultiselectClient(IMultiselectClient):
    """
    Client for communicating with receiver's multiselect
    module in order to select a protocol id to communicate over
    """

    def __init__(self):
        pass

    async def handshake(self, communicator):
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
        handshake_contents = await communicator.read_stream_until_eof()

        # Confirm that the protocols are the same
        if not validate_handshake(handshake_contents):
            raise MultiselectClientError("multiselect protocol ID mismatch")

        # Handshake succeeded if this point is reached

    async def select_protocol_or_fail(self, protocol, stream):
        """
        Send message to multiselect selecting protocol
        and fail if multiselect does not return same protocol
        :param protocol: protocol to select
        :param stream: stream to communicate with multiselect over
        :return: selected protocol
        """

        # Create a communicator to handle all communication across the stream
        communicator = MultiselectCommunicator(stream)

        # Perform handshake to ensure multiselect protocol IDs match
        await self.handshake(communicator)

        # Try to select the given protocol
        selected_protocol = await self.try_select(communicator, protocol)

        return selected_protocol

    async def select_one_of(self, protocols, stream):
        """
        For each protocol, send message to multiselect selecting protocol
        and fail if multiselect does not return same protocol. Returns first
        protocol that multiselect agrees on (i.e. that multiselect selects)
        :param protocol: protocol to select
        :param stream: stream to communicate with multiselect over
        :return: selected protocol
        """

        # Create a communicator to handle all communication across the stream
        communicator = MultiselectCommunicator(stream)

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

    async def try_select(self, communicator, protocol):
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
        response = await communicator.read_stream_until_eof()

        # Return protocol if response is equal to protocol or raise error
        if response == protocol:
            return protocol
        if response == PROTOCOL_NOT_FOUND_MSG:
            raise MultiselectClientError("protocol not supported")
        else:
            raise MultiselectClientError("unrecognized response: " + response)


def validate_handshake(handshake_contents):
    """
    Determine if handshake is valid and should be confirmed
    :param handshake_contents: contents of handshake message
    :return: true if handshake is complete, false otherwise
    """

    # TODO: Modify this when format used by go repo for messages
    # is added
    return handshake_contents == MULTISELECT_PROTOCOL_ID

class MultiselectClientError(ValueError):
    """Raised when an error occurs in protocol selection process"""
