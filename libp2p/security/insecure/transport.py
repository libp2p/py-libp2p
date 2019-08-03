from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.base_session import BaseSession
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.secure_conn_interface import ISecureConn


class InsecureSession(BaseSession):
    @property
    def writer(self):
        return self.insecure_conn.writer

    @property
    def reader(self):
        return self.insecure_conn.reader

    async def write(self, data: bytes) -> None:
        await self.insecure_conn.write(data)

    async def read(self) -> bytes:
        return await self.insecure_conn.read()


class InsecureTransport(BaseSecureTransport):
    """
    ``InsecureTransport`` provides the "identity" upgrader for a ``IRawConnection``,
    i.e. the upgraded transport does not add any additional security.
    """

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are not the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        return InsecureSession(self, conn, ID(b""))

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        return InsecureSession(self, conn, peer_id)
