from typing import Dict, List, Mapping, Type

from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.network.typing import GenericProtocolHandlerFn
from libp2p.peer.id import ID
from libp2p.protocol_muxer.multiselect import Multiselect
from libp2p.protocol_muxer.multiselect_client import MultiselectClient
from libp2p.protocol_muxer.multiselect_communicator import RawConnectionCommunicator
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.typing import TProtocol

from .abc import IMuxedConn

MuxerClassType = Type[IMuxedConn]

# FIXME: add negotiate timeout to `MuxerMultistream`
DEFAULT_NEGOTIATE_TIMEOUT = 60


class MuxerMultistream:
    """
    MuxerMultistream is a multistream stream muxed transport multiplexer.
    go implementation: github.com/libp2p/go-stream-muxer-multistream/multistream.go
    """

    transports: Dict[TProtocol, MuxerClassType]
    multiselect: Multiselect
    multiselect_client: MultiselectClient
    order_preference: List[TProtocol]

    def __init__(
        self, muxer_transports_by_protocol: Mapping[TProtocol, MuxerClassType]
    ) -> None:
        self.transports = {}
        self.multiselect = Multiselect()
        self.multiselect_client = MultiselectClient()
        self.order_preference = []
        for protocol, transport in muxer_transports_by_protocol.items():
            self.add_transport(protocol, transport)

    def add_transport(self, protocol: TProtocol, transport: MuxerClassType) -> None:
        self.transports[protocol] = transport
        self.multiselect.add_handler(protocol, None)
        self.order_preference.append(protocol)

    async def select_transport(self, conn: IRawConnection) -> MuxerClassType:
        """
        Select a transport that both us and the node on the
        other end of conn support and agree on
        :param conn: conn to choose a transport over
        :param initiator: true if we are the initiator, false otherwise
        :return: selected secure transport
        """
        protocol: TProtocol
        communicator = RawConnectionCommunicator(conn)
        if conn.initiator:
            protocol = await self.multiselect_client.select_one_of(
                self.order_preference, communicator
            )
        else:
            protocol, _ = await self.multiselect.negotiate(communicator)
        return self.transports[protocol]

    async def new_conn(
        self,
        conn: ISecureConn,
        generic_protocol_handler: GenericProtocolHandlerFn,
        peer_id: ID,
    ) -> IMuxedConn:
        transport_class = await self.select_transport(conn)
        return transport_class(conn, generic_protocol_handler, peer_id)
