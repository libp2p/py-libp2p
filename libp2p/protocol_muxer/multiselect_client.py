from typing import Sequence

from libp2p.stream_muxer.abc import IMuxedStream
from libp2p.typing import NegotiableTransport, TProtocol

from .multiselect_client_interface import IMultiselectClient
from .multiselect_communicator import MultiselectCommunicator
from .multiselect_communicator_interface import IMultiselectCommunicator
from .utils import delim_read, delim_write

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
        rwtor = communicator.reader_writer
        await delim_write(rwtor.writer, MULTISELECT_PROTOCOL_ID)

        # Read in the protocol ID from other party
        # handshake_contents = await communicator.read_stream_until_eof()
        handshake_contents = await delim_read(rwtor.reader)

        print(
            f"!@# multiselect_client.handshake: handshake_contents={handshake_contents}"
        )
        # Confirm that the protocols are the same
        if not validate_handshake(handshake_contents):
            raise MultiselectClientError("multiselect protocol ID mismatch")

        # Handshake succeeded if this point is reached

    async def select_protocol_or_fail(
        self, protocol: TProtocol, stream: IMuxedStream
    ) -> TProtocol:
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

    async def select_one_of(
        self, protocols: Sequence[TProtocol], stream: NegotiableTransport
    ) -> TProtocol:
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
        rwtor = communicator.reader_writer
        await delim_write(rwtor.writer, protocol)

        # Get what counterparty says in response
        response = await delim_read(rwtor.reader)

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


class MultiselectClientError(ValueError):
    """Raised when an error occurs in protocol selection process"""
