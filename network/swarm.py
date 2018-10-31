from .network_interface import INetwork
from ..connection.muxed_connection import MuxedConnection
from ..connection.raw_connection import RawConnection

class Swarm(INetwork):

    def __init__(self, my_peer_id, peer_store):
        self.my_peer_id = my_peer_id
        self.peer_store = peer_store
        self.connections = {}

    def set_stream_handler(self, stream_handler):
        """
        :param stream_handler: a stream handler instance
        :return: true if successful
        """
        pass

    def new_stream(self, peer_id, protocol_id):
        """
        Determine if a connection to peer_id already exists
        If a connection to peer_id exists, then
        c = existing connection,
        otherwise c = new muxed connection to peer_id
        s = c.open_stream(protocol_id)
        return s

        :param peer_id: peer_id of destination
        :param protocol_id: protocol id
        :return: stream instance
        """
        muxed_connection = None
        if peer_id in self.connections:
            muxed_connection = self.connections[peer_id]
        else:
            addrs = self.peer_store.addrs(peer_id)
            stream_ip = addrs.get_protocol_value("ip")
            stream_port = addrs.get_protocol_value("port")
            if len(addrs) > 0:
                conn = RawConnection(stream_ip, stream_port)
                muxed_connection = MuxedConnection(conn, True)
            else:
                raise Exception("No IP and port in addr")
        return muxed_connection.open_stream(protocol_id, "")

    def listen(self, *args):
        """
        :param *args: one or many multiaddrs to start listening on
        :return: true if at least one success
        """
        pass
