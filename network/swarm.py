from .network_interface import INetwork
from muxer.mplex.muxed_connection import MuxedConn
from transport.connection.raw_connection import RawConnection

class Swarm(INetwork):

    def __init__(self, my_peer_id, peerstore, upgrader):
        self.my_peer_id = my_peer_id
        self.peerstore = peerstore
        self.connections = {}

    def set_stream_handler(self, stream_handler):
        """
        :param stream_handler: a stream handler instance
        :return: true if successful
        """
        pass

    def new_stream(self, peer_id, protocol_id):
        """
        :param peer_id: peer_id of destination
        :param protocol_id: protocol id
        :return: stream instance
        """
        muxed_connection = None
        if peer_id in self.connections:
            """
            If muxed connection already exists for peer_id,
            set muxed connection equal to 
            existing muxed connection
            """ 
            muxed_connection = self.connections[peer_id]
        else:
            addrs = self.peerstore.addrs(peer_id)
            stream_ip = addrs.get_protocol_value("ip")
            stream_port = addrs.get_protocol_value("port")
            if len(addrs) > 0:
                conn = RawConnection(stream_ip, stream_port)
                muxed_connection = MuxedConnection(conn, True)
            else:
                raise Exception("No IP and port in addr")
        return muxed_connection.open_stream(protocol_id, "", peer_id, addrs)

    def listen(self, *args):
        """
        :param *args: one or many multiaddrs to start listening on
        :return: true if at least one success
        """
        pass
