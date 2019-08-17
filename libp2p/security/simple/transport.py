import asyncio

from libp2p.crypto.keys import KeyPair
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.base_transport import BaseSecureTransport
from libp2p.security.insecure.transport import InsecureSession
from libp2p.security.secure_conn_interface import ISecureConn


class SimpleSecurityTransport(BaseSecureTransport):
    key_phrase: str

    def __init__(self, local_key_pair: KeyPair, key_phrase: str) -> None:
        super().__init__(local_key_pair)
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

        session = InsecureSession(self, conn, ID(b""))
        # TODO: Calls handshake to make them know the peer id each other, otherwise tests fail.
        #   However, it seems pretty weird that `SimpleSecurityTransport` sends peer id through
        #   `Insecure`.
        await session.run_handshake()
        # NOTE: this is abusing the abstraction we have here
        # but this code may be deprecated soon and this exists
        # mainly to satisfy a test that will go along w/ it
        # FIXME: Enable type check back when we can deprecate the simple transport.
        session.key_phrase = self.key_phrase  # type: ignore
        return session

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

        session = InsecureSession(self, conn, peer_id)
        # TODO: Calls handshake to make them know the peer id each other, otherwise tests fail.
        #   However, it seems pretty weird that `SimpleSecurityTransport` sends peer id through
        #   `Insecure`.
        await session.run_handshake()
        # NOTE: this is abusing the abstraction we have here
        # but this code may be deprecated soon and this exists
        # mainly to satisfy a test that will go along w/ it
        # FIXME: Enable type check back when we can deprecate the simple transport.
        session.key_phrase = self.key_phrase  # type: ignore
        return session
