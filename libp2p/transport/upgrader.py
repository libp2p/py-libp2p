from typing import Mapping, Sequence

from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.network.typing import GenericProtocolHandlerFn
from libp2p.peer.id import ID
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.security.secure_transport_interface import ISecureTransport
from libp2p.security.security_multistream import SecurityMultistream
from libp2p.stream_muxer.mplex.mplex import Mplex
from libp2p.typing import TProtocol

from .listener_interface import IListener
from .transport_interface import ITransport
from libp2p.stream_muxer.muxed_multistream import (
    MuxedMultistream,
)


class TransportUpgrader:
    security_multistream: SecurityMultistream
    muxed_multistream: MuxedMultistream
    muxer: Sequence[str]

    def __init__(
        self, secOpt: Mapping[TProtocol, ISecureTransport], muxerOpt: Sequence[str]
    ) -> None:
        # Store security option
        self.security_multistream = SecurityMultistream()
        for key, value in secOpt.items():
            self.security_multistream.add_transport(key, value)
        # Store muxer option
        # muxerOpt = ["mplex/6.7.0"]
        # /yamux/1.0.0 /mplex/6.7.0
        self.muxed_multistream = MuxedMultistream()
        for key, value in muxerOpt.items():
            self.muxed_multistream.add_transport(key, value)

    def upgrade_listener(self, transport: ITransport, listeners: IListener) -> None:
        """
        Upgrade multiaddr listeners to libp2p-transport listeners
        """
        pass

    async def upgrade_security(
        self, raw_conn: IRawConnection, peer_id: ID, initiator: bool
    ) -> ISecureConn:
        """
        Upgrade conn to be a secured connection
        """
        if initiator:
            return await self.security_multistream.secure_outbound(raw_conn, peer_id)

        return await self.security_multistream.secure_inbound(raw_conn)

    def upgrade_connection(
        self,
        conn: ISecureConn,
        generic_protocol_handler: GenericProtocolHandlerFn,
        peer_id: ID,
        initiator: bool,
    ) -> Mplex:
        """
        Upgrade conn to be a muxed connection
        """
        return await self.muxed_multistream.new_conn(
            conn,
            generic_protocol_handler,
            peer_id,
            initiator,
        )
