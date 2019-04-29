from libp2p.stream_muxer.mplex.mplex import Mplex


class TransportUpgrader:
    # pylint: disable=no-self-use

    def __init__(self, secOpt, muxerOpt):
        self.sec = secOpt
        self.muxer = muxerOpt

    def upgrade_listener(self, transport, listeners):
        """
        Upgrade multiaddr listeners to libp2p-transport listeners
        """

    def upgrade_security(self, conn, peer_id):
        """
        Upgrade conn to be a secured connection
        """
        # TODO: Do exchange to determine security module
        pass

    def upgrade_connection(self, conn, generic_protocol_handler, peer_id):
        """
        Upgrade raw connection to muxed connection
        """

        # For PoC, no security, default to mplex
        # TODO do exchange to determine multiplexer
        return Mplex(conn, generic_protocol_handler, peer_id)
