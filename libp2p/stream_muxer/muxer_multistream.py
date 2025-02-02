from collections import (
    OrderedDict,
)

from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.connection.raw_connection_interface import (
    IRawConnection,
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
from libp2p.security.secure_conn_interface import (
    ISecureConn,
)
from libp2p.transport.typing import (
    TMuxerClass,
    TMuxerOptions,
)

from .abc import (
    IMuxedConn,
)

# FIXME: add negotiate timeout to `MuxerMultistream`
DEFAULT_NEGOTIATE_TIMEOUT = 60


class MuxerMultistream:
    """
    MuxerMultistream is a multistream stream muxed transport multiplexer.

    go implementation: github.com/libp2p/go-stream-muxer-multistream/multistream.go
    """

    # NOTE: Can be changed to `typing.OrderedDict` since Python 3.7.2.
    transports: "OrderedDict[TProtocol, TMuxerClass]"
    multiselect: Multiselect
    multiselect_client: MultiselectClient

    def __init__(self, muxer_transports_by_protocol: TMuxerOptions) -> None:
        self.transports = OrderedDict()
        self.multiselect = Multiselect()
        self.multiselect_client = MultiselectClient()
        for protocol, transport in muxer_transports_by_protocol.items():
            self.add_transport(protocol, transport)

    def add_transport(self, protocol: TProtocol, transport: TMuxerClass) -> None:
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
        self.multiselect.add_handler(protocol, None)

    async def select_transport(self, conn: IRawConnection) -> TMuxerClass:
        """
        Select a transport that both us and the node on the other end of conn
        support and agree on.

        :param conn: conn to choose a transport over
        :return: selected muxer transport
        """
        protocol: TProtocol
        communicator = MultiselectCommunicator(conn)
        if conn.is_initiator:
            protocol = await self.multiselect_client.select_one_of(
                tuple(self.transports.keys()), communicator
            )
        else:
            protocol, _ = await self.multiselect.negotiate(communicator)
        return self.transports[protocol]

    async def new_conn(self, conn: ISecureConn, peer_id: ID) -> IMuxedConn:
        transport_class = await self.select_transport(conn)
        return transport_class(conn, peer_id)
