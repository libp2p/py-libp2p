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


class TransportUpgrader:
    security_multistream: SecurityMultistream
    muxer: Sequence[str]

    def __init__(
        self,
        secure_transports_by_protocol: Mapping[TProtocol, ISecureTransport],
        muxerOpt: Sequence[str],
    ):
        self.security_multistream = SecurityMultistream(secure_transports_by_protocol)
        self.muxer = muxerOpt

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

    @staticmethod
    def upgrade_connection(
        conn: ISecureConn,
        generic_protocol_handler: GenericProtocolHandlerFn,
        peer_id: ID,
    ) -> Mplex:
        """
        Upgrade raw connection to muxed connection
        """
        # TODO do exchange to determine multiplexer
        return Mplex(conn, generic_protocol_handler, peer_id)
