from libp2p.security.security_multistream import SecurityMultistream
from libp2p.stream_muxer.mplex.mplex import Mplex

from typing import TYPE_CHECKING

if TYPE_CHECKING:

    from typing import Dict, Sequence
    from libp2p.network.connection.raw_connection_interface import IRawConnection
    from libp2p.network.swarm import GenericProtocolHandlerFn
    from libp2p.peer.id import ID
    from libp2p.security.secure_conn_interface import ISecureConn
    from libp2p.security.secure_transport_interface import ISecureTransport
    from libp2p.security.security_multistream import TProtocol
    from .transport_interface import ITransport
    from .listener_interface import IListener


class TransportUpgrader:
    security_multistream: SecurityMultistream
    muxer: "Sequence[str]"

    def __init__(
        self, secOpt: "Dict[TProtocol, ISecureTransport]", muxerOpt: "Sequence[str]"
    ) -> None:
        # Store security option
        self.security_multistream = SecurityMultistream()
        for key in secOpt:
            self.security_multistream.add_transport(key, secOpt[key])

        # Store muxer option
        self.muxer = muxerOpt

    def upgrade_listener(self, transport: "ITransport", listeners: "IListener") -> None:
        """
        Upgrade multiaddr listeners to libp2p-transport listeners
        """
        pass

    async def upgrade_security(
        self, raw_conn: "IRawConnection", peer_id: "ID", initiator: bool
    ) -> "ISecureConn":
        """
        Upgrade conn to be a secured connection
        """
        if initiator:
            return await self.security_multistream.secure_outbound(raw_conn, peer_id)

        return await self.security_multistream.secure_inbound(raw_conn)

    @staticmethod
    def upgrade_connection(
        conn: "IRawConnection",
        generic_protocol_handler: "GenericProtocolHandlerFn",
        peer_id: "ID",
    ) -> "Mplex":
        """
        Upgrade raw connection to muxed connection
        """

        # For PoC, no security, default to mplex
        # TODO do exchange to determine multiplexer
        return Mplex(conn, generic_protocol_handler, peer_id)
