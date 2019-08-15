from typing import Dict, Tuple

from libp2p.typing import NegotiableTransport, StreamHandlerFn, TProtocol

from .multiselect_communicator import MultiselectCommunicator
from .multiselect_communicator_interface import IMultiselectCommunicator
from .multiselect_muxer_interface import IMultiselectMuxer
from .utils import delim_read, encode_delim

MULTISELECT_PROTOCOL_ID = "/multistream/1.0.0"
PROTOCOL_NOT_FOUND_MSG = "na"


class Multiselect(IMultiselectMuxer):
    """
    Multiselect module that is responsible for responding to
    a multiselect client and deciding on
    a specific protocol and handler pair to use for communication
    """

    handlers: Dict[TProtocol, StreamHandlerFn]

    def __init__(self) -> None:
        self.handlers = {}

    def add_handler(self, protocol: TProtocol, handler: StreamHandlerFn) -> None:
        """
        Store the handler with the given protocol
        :param protocol: protocol name
        :param handler: handler function
        """
        self.handlers[protocol] = handler

    async def negotiate(
        self, stream: NegotiableTransport
    ) -> Tuple[TProtocol, StreamHandlerFn]:
        """
        Negotiate performs protocol selection
        :param stream: stream to negotiate on
        :return: selected protocol name, handler function
        :raise Exception: negotiation failed exception
        """
        # Create a communicator to handle all communication across the stream
        communicator = MultiselectCommunicator(stream)

        # Perform handshake to ensure multiselect protocol IDs match
        await self.handshake(communicator)

        # Read and respond to commands until a valid protocol ID is sent
        while True:
            # Read message
            print("!@# Multiselect.negotiate.read: wait for command")
            command = await delim_read(communicator.reader_writer)
            print(f"!@# Multiselect.negotiate.read: command={command}")

            # Command is ls or a protocol
            if command == "ls":
                # TODO: handle ls command
                pass
            else:
                protocol = TProtocol(command)
                if protocol in self.handlers:
                    print(f"!@# protocol={protocol}")
                    # Tell counterparty we have decided on a protocol
                    await communicator.write(encode_delim(protocol).decode())

                    # Return the decided on protocol
                    return protocol, self.handlers[protocol]
                # Tell counterparty this protocol was not found
                await communicator.write(encode_delim(PROTOCOL_NOT_FOUND_MSG).decode())

    async def handshake(self, communicator: IMultiselectCommunicator) -> None:
        """
        Perform handshake to agree on multiselect protocol
        :param communicator: communicator to use
        :raise Exception: error in handshake
        """

        # TODO: Use format used by go repo for messages

        print("!@# multiselect-server.handshake: writing `PROTOCOL_ID`")
        # Send our MULTISELECT_PROTOCOL_ID to other party
        await communicator.write(encode_delim(MULTISELECT_PROTOCOL_ID).decode())
        print(f"!@# type(communicator)={type(communicator.reader_writer)}")

        # Read in the protocol ID from other party
        print("!@# multiselect-server.handshake: wait for handshake_contents")
        handshake_contents = await delim_read(communicator.reader_writer)
        print(
            f"!@# multiselect-server.handshake: handshake_contents={handshake_contents}"
        )

        # Confirm that the protocols are the same
        if not validate_handshake(handshake_contents):
            raise MultiselectError("multiselect protocol ID mismatch")

        # Handshake succeeded if this point is reached


def validate_handshake(handshake_contents: str) -> bool:
    """
    Determine if handshake is valid and should be confirmed
    :param handshake_contents: contents of handshake message
    :return: true if handshake is complete, false otherwise
    """

    # TODO: Modify this when format used by go repo for messages
    # is added
    return handshake_contents == MULTISELECT_PROTOCOL_ID


class MultiselectError(ValueError):
    """Raised when an error occurs in multiselect process"""
