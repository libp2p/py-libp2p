from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.protocol_muxer.exceptions import MultiselectClientError, MultiselectError
from libp2p.security.exceptions import HandshakeFailure
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.security.security_multistream import SecurityMultistream
from libp2p.stream_muxer.abc import IMuxedConn
from libp2p.stream_muxer.muxer_multistream import MuxerMultistream
from libp2p.transport.exceptions import MuxerUpgradeFailure, SecurityUpgradeFailure
from libp2p.transport.typing import TMuxerOptions, TSecurityOptions

from .listener_interface import IListener
from .transport_interface import ITransport


class TransportUpgrader:
    security_multistream: SecurityMultistream
    muxer_multistream: MuxerMultistream

    def __init__(
        self,
        secure_transports_by_protocol: TSecurityOptions,
        muxer_transports_by_protocol: TMuxerOptions,
    ):
        self.security_multistream = SecurityMultistream(secure_transports_by_protocol)
        self.muxer_multistream = MuxerMultistream(muxer_transports_by_protocol)

    def upgrade_listener(self, transport: ITransport, listeners: IListener) -> None:
        """Upgrade multiaddr listeners to libp2p-transport listeners."""
        # TODO: Figure out what to do with this function.
        pass

    async def upgrade_security(
        self, raw_conn: IRawConnection, peer_id: ID, is_initiator: bool
    ) -> ISecureConn:
        """Upgrade conn to a secured connection."""
        try:
            if is_initiator:
                return await self.security_multistream.secure_outbound(
                    raw_conn, peer_id
                )
            return await self.security_multistream.secure_inbound(raw_conn)
        except (MultiselectError, MultiselectClientError) as error:
            raise SecurityUpgradeFailure(
                "failed to negotiate the secure protocol"
            ) from error
        except HandshakeFailure as error:
            raise SecurityUpgradeFailure(
                "handshake failed when upgrading to secure connection"
            ) from error

    async def upgrade_connection(self, conn: ISecureConn, peer_id: ID) -> IMuxedConn:
        """Upgrade secured connection to a muxed connection."""
        try:
            return await self.muxer_multistream.new_conn(conn, peer_id)
        except (MultiselectError, MultiselectClientError) as error:
            raise MuxerUpgradeFailure(
                "failed to negotiate the multiplexer protocol"
            ) from error
