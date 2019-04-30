import asyncio

from abc import ABC, abstractmethod
from libp2p.protocol_muxer.multiselect_client import MultiselectClient
from libp2p.protocol_muxer.multiselect import Multiselect

"""
Represents a secured connection object, which includes a connection and details about the security
involved in the secured connection

Relevant go repo: https://github.com/libp2p/go-conn-security/blob/master/interface.go
"""
class SecurityMultistream(ABC):

    def __init__(self):
        # Map protocol to secure transport 
        self.transports = {}

        # Create multiselect
        self.multiselect = Multiselect()

        # Create multiselect client
        self.multiselect_client = MultiselectClient()

    def add_transport(self, protocol, transport):
        # Associate protocol with transport
        self.transports[protocol] = transport

        # Add protocol and handler to multiselect
        # Note: None is added as the handler for the given protocol since
        # we only care about selecting the protocol, not any handler function
        self.multiselect.add_handler(protocol, None)

    
    async def secure_inbound(self, conn):
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are not the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """

        # Select a secure transport
        transport = await self.select_transport(conn, True)

        # Create secured connection
        secure_conn = await transport.secure_inbound(conn)

        return secure_conn


    async def secure_outbound(self, conn, peer_id):
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """

        # Select a secure transport
        transport = await self.select_transport(conn, True)

        # Create secured connection
        secure_conn = await transport.secure_outbound(conn, peer_id)

        return secure_conn


    async def select_transport(self, conn, initiator):
        """
        Select a transport that both us and the node on the 
        other end of conn support and agree on
        :param conn: conn to choose a transport over
        :param initiator: true if we are the initiator, false otherwise
        :return: selected secure transport
        """
        # TODO: Is conn acceptable to multiselect/multiselect_client instead of stream? In go repo,
        # they pass in a raw conn (https://raw.githubusercontent.com/libp2p/go-conn-security-multistream/master/ssms.go)
        
        protocol = None
        if initiator:
            # Select protocol if initiator
            protocol = await self.multiselect_client.select_one_of(list(self.transports.keys()), conn)
        else:
            # Select protocol if non-initiator
            protocol = await self.multiselect.negotiate(conn)

        # Return transport from protocol
        return self.transports[protocol]
