from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.security.secure_transport_interface import ISecureTransport


class InsecureTransport(ISecureTransport):
    def __init__(self, transport_id):
        self.transport_id = transport_id

    async def secure_inbound(self, conn):
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are not the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        insecure_conn = InsecureConn(conn, self.transport_id)
        return insecure_conn

    async def secure_outbound(self, conn, peer_id):
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        insecure_conn = InsecureConn(conn, self.transport_id)
        return insecure_conn


class InsecureConn(ISecureConn):
    def __init__(self, conn, conn_id):
        self.conn = conn
        self.details = {}
        self.details["id"] = conn_id

    def get_conn(self):
        """
        :return: connection object that has been made secure
        """
        return self.conn

    def get_security_details(self):
        """
        :return: map containing details about the connections security
        """
        return self.details
