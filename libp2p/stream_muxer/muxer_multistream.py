from collections import (
    OrderedDict,
)
import logging

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
from libp2p.protocol_muxer.exceptions import (
    MultiselectClientError,
    MultiselectError,
)
from libp2p.protocol_muxer.generic_selector import (
    GenericMultistreamSelector,
)
from libp2p.protocol_muxer.multiselect import (
    DEFAULT_NEGOTIATE_TIMEOUT,
    Multiselect,
)
from libp2p.protocol_muxer.multiselect_client import (
    MultiselectClient,
)
from libp2p.stream_muxer.yamux.yamux import (
    PROTOCOL_ID,
    Yamux,
)

logger = logging.getLogger(__name__)


class MuxerMultistream:
    """
    MuxerMultistream is a multistream stream muxed transport multiplexer.

    go implementation: github.com/libp2p/go-stream-muxer-multistream/multistream.go
    """

    _selector: "GenericMultistreamSelector[TMuxerClass]"
    negotiate_timeout: int

    def __init__(
        self,
        muxer_transports_by_protocol: TMuxerOptions,
        negotiate_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
    ) -> None:
        self._selector = GenericMultistreamSelector()
        self.negotiate_timeout = negotiate_timeout
        for protocol, transport in muxer_transports_by_protocol.items():
            self.add_transport(protocol, transport)

    @property
    def transports(self) -> "OrderedDict[TProtocol, TMuxerClass]":
        return self._selector.handlers

    @property
    def multiselect(self) -> Multiselect:
        return self._selector.multiselect

    @property
    def multiselect_client(self) -> MultiselectClient:
        return self._selector.multiselect_client

    @property
    def multistream_client(self) -> MultiselectClient:
        """
        Backwards-compatible alias for ``multiselect_client``.

        Deprecated: use ``multiselect_client`` instead.
        """
        return self.multiselect_client

    def add_transport(self, protocol: TProtocol, transport: TMuxerClass) -> None:
        """
        Add a protocol and its corresponding transport to multistream-
        select(multiselect). The order that a protocol is added is exactly the
        precedence it is negotiated in multiselect.

        :param protocol: the protocol name, which is negotiated in multiselect.
        :param transport: the corresponding transportation to the ``protocol``.
        """
        self._selector.add_handler(protocol, transport)

    async def select_transport(self, conn: IRawConnection) -> TMuxerClass:
        """
        Select a transport that both us and the node on the other end of conn
        support and agree on.

        :param conn: conn to choose a transport over
        :return: selected muxer transport
        """
        try:
            _, transport = await self._selector.select(
                conn, conn.is_initiator, self.negotiate_timeout
            )
        except (MultiselectError, MultiselectClientError) as error:
            raise MultiselectError(
                "Failed to negotiate a stream muxer protocol: no protocol selected"
            ) from error
        return transport

    async def new_conn(self, conn: ISecureConn, peer_id: ID) -> IMuxedConn:
        logger.debug(
            "MuxerMultistream: muxer negotiation peer=%s initiator=%s",
            peer_id,
            conn.is_initiator,
        )
        protocol, transport_class = await self._selector.select(
            conn, conn.is_initiator, self.negotiate_timeout
        )
        logger.debug("MuxerMultistream new_conn: negotiated protocol %s", protocol)
        if protocol == PROTOCOL_ID:
            async with trio.open_nursery():

                async def on_close() -> None:
                    pass

                return Yamux(
                    conn, peer_id, is_initiator=conn.is_initiator, on_close=on_close
                )
        return transport_class(conn, peer_id)
