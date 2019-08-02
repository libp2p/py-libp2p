from typing import cast

from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.security.secure_transport_interface import ISecureTransport
from libp2p.security.typing import TSecurityDetails


class InsecureTransport(ISecureTransport):
    """
    ``InsecureTransport`` provides the "identity" upgrader for a ``IRawConnection``,
    i.e. the upgraded transport does not add any additional security.
    """

    transport_id: str

    def __init__(self, transport_id: str) -> None:
        self.transport_id = transport_id

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are not the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        insecure_conn = InsecureConn(conn, self.transport_id)
        return insecure_conn

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        insecure_conn = InsecureConn(conn, self.transport_id)
        return insecure_conn


class InsecureConn(ISecureConn):
    conn: IRawConnection
    details: TSecurityDetails

    def __init__(self, conn: IRawConnection, conn_id: str) -> None:
        self.conn = conn
        self.details = cast(TSecurityDetails, {})
        self.details["id"] = conn_id

    def get_conn(self) -> IRawConnection:
        """
        :return: connection object that has been made secure
        """
        return self.conn

    def get_security_details(self) -> TSecurityDetails:
        """
        :return: map containing details about the connections security
        """
        return self.details
