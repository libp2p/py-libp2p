import asyncio
from libp2p.security.secure_transport_interface import ISecureTransport
from libp2p.security.secure_conn_interface import ISecureConn


class SimpleSecurityTransport(ISecureTransport):
    def __init__(self, key_phrase):
        self.key_phrase = key_phrase

    async def secure_inbound(self, conn):
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

        secure_conn = SimpleSecureConn(conn, self.key_phrase)
        return secure_conn

    async def secure_outbound(self, conn, peer_id):
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

        secure_conn = SimpleSecureConn(conn, self.key_phrase)
        return secure_conn


class SimpleSecureConn(ISecureConn):
    def __init__(self, conn, key_phrase):
        self.conn = conn
        self.details = {}
        self.details["key_phrase"] = key_phrase

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
