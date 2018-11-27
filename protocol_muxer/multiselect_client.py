from .multiselect_client_interface import IMultiselectClient
from .multiselect_communicator import MultiselectCommunicator

class MultiselectClient(IMultiselectClient):

    def __init__(self):
        self.MULTISELECT_PROTOCOL_ID = "/multistream/1.0.0"
        self.PROTOCOL_NOT_FOUND_MSG = "na"
    
    async def handshake(self, communicator):
        # TODO: Use format used by go repo for messages

        # Send our MULTISELECT_PROTOCOL_ID to counterparty
        await communicator.write(self.MULTISELECT_PROTOCOL_ID)

        # Read in the protocol ID from other party
        handshake_contents = await communicator.read_stream_until_eof()
        
        # Confirm that the protocols are the same
        if not(self.validate_handshake(handshake_contents)):
            raise MultiselectClientError("multiselect protocol ID mismatch")

        # Handshake succeeded if this point is reached

    def validate_handshake(self, handshake_contents):
        # TODO: Modify this when format used by go repo for messages
        # is added
        return handshake_contents == self.MULTISELECT_PROTOCOL_ID

    async def select_proto_or_fail(self, protocol, stream): 
        # Create a communicator to handle all communication across the stream
        communicator = MultiselectCommunicator(stream)

        # Perform handshake to ensure multiselect protocol IDs match
        await self.handshake(communicator)

        # Try to select the given protocol
        selected_protocol = await self.try_select(communicator, protocol)

        return selected_protocol

    async def select_one_of(self, protocols, stream):
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
            except Exception:
                pass

        # No protocols were found, so return no protocols supported error
        raise MultiselectClientError("protocols not supported")

    async def try_select(self, communicator, protocol):
        # Tell counterparty we want to use protocol
        await communicator.write(protocol)

        # Get what counterparty says in response
        response = await communicator.read_stream_until_eof()

        # Return protocol if response is equal to protocol or raise error
        if response == protocol:
            return protocol
        elif response == self.PROTOCOL_NOT_FOUND_MSG:
            raise MultiselectClientError("protocol not supported")
        else:
            raise MultiselectClientError("unrecognized response: " + response)

class MultiselectClientError(ValueError):
    """Raised when an error occurs in protocol selection process"""
    pass
