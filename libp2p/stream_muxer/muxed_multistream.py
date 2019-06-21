from typing import (
    Dict,
    List,
    Type,
)

from libp2p.network.connection.raw_connection_interface import (
    IRawConnection,
)
from libp2p.protocol_muxer.multiselect import Multiselect
from libp2p.protocol_muxer.multiselect_client import MultiselectClient
from libp2p.security.secure_conn_interface import ISecureConn

from .muxed_connection_interface import (
    IMuxedConn,
)


MuxerClassType = Type[IMuxedConn]

# FIXME: add negotiate timeout to `MuxedMultistream`
DEFAULT_NEGOTIATE_TIMEOUT = 60


class MuxedMultistream:
    """
    MuxedMultistream is a multistream stream muxed transport multiplexer.
    go implementation: github.com/libp2p/go-stream-muxer-multistream/multistream.go
    """

    transports: Dict[str, MuxerClassType]
    multiselect: Multiselect
    multiselect_client: MultiselectClient
    order_preference: List[str]

    def __init__(self) -> None:
        self.transports = {}
        self.multiselect = Multiselect()
        self.multiselect_client = MultiselectClient()
        self.order_preference = []

    def add_transport(self, protocol: str, transport: MuxerClassType) -> None:
        self.transports[protocol] = transport
        self.multiselect.add_handler(protocol, None)
        self.order_preference.append(protocol)

    async def select_transport(self, conn: IRawConnection, initiator: bool) -> MuxerClassType:
        """
        Select a transport that both us and the node on the
        other end of conn support and agree on
        :param conn: conn to choose a transport over
        :param initiator: true if we are the initiator, false otherwise
        :return: selected secure transport
        """
        protocol = None
        if initiator:
            protocol = await self.multiselect_client.select_one_of(
                self.order_preference,
                conn,
            )
        else:
            protocol, _ = await self.multiselect.negotiate(conn)
        return self.transports[protocol]

    async def new_conn(
            self,
            conn: ISecureConn,
            generic_protocol_handler,
            peer_id,
            initiator: bool) -> IMuxedConn:
        transport_class = await self.select_transport(conn.conn, initiator)
        return transport_class(conn, generic_protocol_handler, peer_id)
