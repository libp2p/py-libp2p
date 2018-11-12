from muxer.mplex.muxed_connection import MuxedConn


class TransportUpgrader():

    def __init__(self, secOpt, muxerOpt):
        self.sec = secOpt
        self.muxer = muxerOpt

    def upgrade_listener(self, transport, listeners):
        """
        upgrade multiaddr listeners to libp2p-transport listeners

        """
        pass

    def upgrade_security(self):
        pass

    def upgrade_connection(self, conn, initiator):
        """
        upgrade raw connection to muxed connection
        """

        # For PoC, no security, default to mplex
        # TODO do exchange to determine multiplexer
        return MuxedConn(conn, initiator)
