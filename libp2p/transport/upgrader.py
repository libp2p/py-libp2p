from libp2p.abc import (
    IListener,
    IMuxedConn,
    IRawConnection,
    ISecureConn,
    ITransport,
)
from libp2p.custom_types import (
    TMuxerOptions,
    TSecurityOptions,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.protocol_muxer.exceptions import (
    MultiselectClientError,
    MultiselectError,
)
from libp2p.security.exceptions import (
    HandshakeFailure,
)
from libp2p.security.security_multistream import (
    SecurityMultistream,
)
from libp2p.stream_muxer.muxer_multistream import (
    MuxerMultistream,
)
from libp2p.transport.exceptions import (
    MuxerUpgradeFailure,
    SecurityUpgradeFailure,
)


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

    def upgrade_listener(self, transport: ITransport, listener: IListener) -> IListener:
        """
        Wrap the listener's handler so that all incoming connections are upgraded (secured, then muxed)
        before being passed to the original handler.
        """
        # This assumes the listener has a handler attribute (as in TCPListener)
        original_handler = getattr(listener, "handler", None)
        if original_handler is None:
            raise ValueError("Listener does not have a handler attribute to wrap.")

        async def upgraded_handler(raw_conn):
            # Upgrade to secure connection
            try:
                secured_conn = await self.upgrade_security(raw_conn, is_initiator=False)
            except Exception as e:
                await raw_conn.close()
                raise
            # Get remote peer id from secure connection
            peer_id = secured_conn.get_remote_peer()
            # Upgrade to muxed connection
            try:
                muxed_conn = await self.upgrade_connection(secured_conn, peer_id)
            except Exception as e:
                await secured_conn.close()
                raise
            # Pass the muxed connection to the original handler
            await original_handler(muxed_conn)

        # Replace the handler on the listener
        setattr(listener, "handler", upgraded_handler)
        return listener

    async def upgrade_security(
        self,
        raw_conn: IRawConnection,
        is_initiator: bool,
        peer_id: ID | None = None,
    ) -> ISecureConn:
        """Upgrade conn to a secured connection."""
        try:
            if is_initiator:
                if peer_id is None:
                    raise ValueError("peer_id must be provided for outbout connection")
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
