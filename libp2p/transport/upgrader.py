from libp2p.stream_muxer.mplex.mplex import Mplex
from libp2p.security.security_multistream import SecurityMultistream


class TransportUpgrader:
    def __init__(self, secure_transports_by_protocol, muxerOpt):
        self.security_multistream = SecurityMultistream(secure_transports_by_protocol)
        self.muxer = muxerOpt

    def upgrade_listener(self, transport, listeners):
        """
        Upgrade multiaddr listeners to libp2p-transport listeners
        """

    async def upgrade_security(self, raw_conn, peer_id, initiator):
        """
        Upgrade conn to be a secured connection
        """
        if initiator:
            return await self.security_multistream.secure_outbound(raw_conn, peer_id)

        return await self.security_multistream.secure_inbound(raw_conn)

    def upgrade_connection(self, conn, generic_protocol_handler, peer_id):
        """
        Upgrade raw connection to muxed connection
        """
        # TODO do exchange to determine multiplexer
        return Mplex(conn, generic_protocol_handler, peer_id)
