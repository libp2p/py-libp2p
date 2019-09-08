from typing import Sequence

import logging

from libp2p.typing import TProtocol

from .exceptions import MultiselectClientError
from .multiselect_client_interface import IMultiselectClient
from .multiselect_communicator_interface import IMultiselectCommunicator

MULTISELECT_PROTOCOL_ID = "/multistream/1.0.0"
PROTOCOL_NOT_FOUND_MSG = "na"


logger = logging.getLogger("trinity.libp2p.multiselect")
logger.setLevel(logging.DEBUG)


class MultiselectClient(IMultiselectClient):
    """
    Client for communicating with receiver's multiselect
    module in order to select a protocol id to communicate over
    """

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
        # Send our MULTISELECT_PROTOCOL_ID to counterparty
        await communicator.write(MULTISELECT_PROTOCOL_ID)

        # Tell counterparty we want to use protocol
        await communicator.write(protocol)

        # Read in the protocol ID from other party
        handshake_contents = await communicator.read()

        # Confirm that the protocols are the same
        if not validate_handshake(handshake_contents):
            raise MultiselectClientError("multiselect protocol ID mismatch")

        # Get what counterparty says in response
        response = await communicator.read()

        # Return protocol if response is equal to protocol or raise error
        if response == protocol:
            return protocol
        if response == PROTOCOL_NOT_FOUND_MSG:
            raise MultiselectClientError("protocol not supported")
        raise MultiselectClientError("unrecognized response: " + response)

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
        # Send our MULTISELECT_PROTOCOL_ID to counterparty
        await communicator.write(MULTISELECT_PROTOCOL_ID)

        for protocol in protocols:
            # Tell counterparty we want to use protocol
            logging.debug(f"Sending candidate protocol: {protocol}")
            await communicator.write(protocol)

        # Read in the protocol ID from other party
        handshake_contents = await communicator.read()

        # Confirm that the protocols are the same
        if not validate_handshake(handshake_contents):
            raise MultiselectClientError("multiselect protocol ID mismatch")

        for protocol in protocols:
            # Get what counterparty says in response
            response = await communicator.read()

            if response == protocol:
                # somehow ignore the other messages before returning?
                logging.debug(f"Successfully negotiated: {protocol}")
                return protocol
            elif response == PROTOCOL_NOT_FOUND_MSG:
                logging.debug(f"Protocol not supported: {protocol} (probably)")
                continue
            else:
                logging.error(
                    f"Received unexpected reponse during protocol handshake: {response}"
                )
            continue

        # No protocols were found, so return no protocols supported error
        raise MultiselectClientError("protocols not supported")


def validate_handshake(handshake_contents: str) -> bool:
    """
    Determine if handshake is valid and should be confirmed
    :param handshake_contents: contents of handshake message
    :return: true if handshake is complete, false otherwise
    """

    # TODO: Modify this when format used by go repo for messages
    # is added
    return handshake_contents == MULTISELECT_PROTOCOL_ID
