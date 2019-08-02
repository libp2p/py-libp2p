import asyncio

from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.security.secure_transport_interface import ISecureTransport


class SimpleSecurityTransport(ISecureTransport):
    key_phrase: str

    def __init__(self, key_phrase: str) -> None:
        self.key_phrase = key_phrase

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are not the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        await conn.write(self.key_phrase.encode())
        incoming = (await conn.read()).decode()

        if incoming != self.key_phrase:
            raise Exception(
                "Key phrase differed between nodes. Expected " + self.key_phrase
            )

        return conn

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        await conn.write(self.key_phrase.encode())
        incoming = (await conn.read()).decode()

        # Force context switch, as this security transport is built for testing locally
        # in a single event loop
        await asyncio.sleep(0)

        if incoming != self.key_phrase:
            raise Exception(
                "Key phrase differed between nodes. Expected " + self.key_phrase
            )

        return conn
