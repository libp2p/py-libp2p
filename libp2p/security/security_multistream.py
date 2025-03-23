from abc import (
    ABC,
)
from collections import (
    OrderedDict,
)

from libp2p.abc import (
    IRawConnection,
    ISecureConn,
    ISecureTransport,
)
from libp2p.custom_types import (
    TProtocol,
    TSecurityOptions,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.protocol_muxer.multiselect import (
    Multiselect,
)
from libp2p.protocol_muxer.multiselect_client import (
    MultiselectClient,
)
from libp2p.protocol_muxer.multiselect_communicator import (
    MultiselectCommunicator,
)

"""
Represents a secured connection object, which includes a connection and details about
the security involved in the secured connection

Relevant go repo: https://github.com/libp2p/go-conn-security/blob/master/interface.go
"""


class SecurityMultistream(ABC):
    """
    SSMuxer is a multistream stream security transport multiplexer.

    Go implementation: github.com/libp2p/go-conn-security-multistream/ssms.go
    """

    transports: "OrderedDict[TProtocol, ISecureTransport]"
    multiselect: Multiselect
    multiselect_client: MultiselectClient

    def __init__(self, secure_transports_by_protocol: TSecurityOptions) -> None:
        self.transports = OrderedDict()
        self.multiselect = Multiselect()
        self.multiselect_client = MultiselectClient()

        for protocol, transport in secure_transports_by_protocol.items():
            self.add_transport(protocol, transport)

    def add_transport(self, protocol: TProtocol, transport: ISecureTransport) -> None:
        """
        Add a protocol and its corresponding transport to multistream-
        select(multiselect). The order that a protocol is added is exactly the
        precedence it is negotiated in multiselect.

        :param protocol: the protocol name, which is negotiated in multiselect.
        :param transport: the corresponding transportation to the ``protocol``.
        """
        # If protocol is already added before, remove it and add it again.
        self.transports.pop(protocol, None)
        self.transports[protocol] = transport
        # Note: None is added as the handler for the given protocol since
        # we only care about selecting the protocol, not any handler function
        self.multiselect.add_handler(protocol, None)

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing
        node via conn, for an inbound connection (i.e. we are not the
        initiator)

        :return: secure connection object (that implements secure_conn_interface)
        """
        transport = await self.select_transport(conn, False)
        secure_conn = await transport.secure_inbound(conn)
        return secure_conn

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing
        node via conn, for an inbound connection (i.e. we are the initiator)

        :return: secure connection object (that implements secure_conn_interface)
        """
        transport = await self.select_transport(conn, True)
        secure_conn = await transport.secure_outbound(conn, peer_id)
        return secure_conn

    async def select_transport(
        self, conn: IRawConnection, is_initiator: bool
    ) -> ISecureTransport:
        """
        Select a transport that both us and the node on the other end of conn
        support and agree on.

        :param conn: conn to choose a transport over
        :param is_initiator: true if we are the initiator, false otherwise
        :return: selected secure transport
        """
        protocol: TProtocol
        communicator = MultiselectCommunicator(conn)
        if is_initiator:
            # Select protocol if initiator
            protocol = await self.multiselect_client.select_one_of(
                list(self.transports.keys()), communicator
            )
        else:
            # Select protocol if non-initiator
            protocol, _ = await self.multiselect.negotiate(communicator)
        # Return transport from protocol
        return self.transports[protocol]
