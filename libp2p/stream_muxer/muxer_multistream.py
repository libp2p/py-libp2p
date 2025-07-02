from collections import (
    OrderedDict,
)

import trio

from libp2p.abc import (
    IMuxedConn,
    IRawConnection,
    ISecureConn,
)
from libp2p.custom_types import (
    TMuxerClass,
    TMuxerOptions,
    TProtocol,
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
from libp2p.stream_muxer.yamux.yamux import (
    PROTOCOL_ID,
    Yamux,
)


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
        self.multistream_client = MultiselectClient()
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
        communicator = MultiselectCommunicator(conn)
        protocol = await self.multistream_client.select_one_of(
            tuple(self.transports.keys()), communicator
        )
        transport_class = self.transports[protocol]
        if protocol == PROTOCOL_ID:
            async with trio.open_nursery():

                async def on_close() -> None:
                    pass

                return Yamux(
                    conn, peer_id, is_initiator=conn.is_initiator, on_close=on_close
                )
        return transport_class(conn, peer_id)
