from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.security.base_session import BaseSession
from libp2p.security.base_transport import BaseSecureTransport


class SecIOSession(BaseSession):
    async def __init__(
        self, transport: BaseSecureTransport, conn: IRawConnection, peer_id: ID
    ) -> None:
        super().__init__(transport, conn, peer_id)
        # TODO set up secio params
        # TODO do exchange
        # TODO verify first message via secio protocol

    @property
    def writer(self):
        # TODO unclear this satisfies the interface we are after
        # NOTE: a solution probably entails a better understanding of how
        # the underlying interface is used across this repo
        return self

    @property
    def reader(self):
        # TODO unclear this satisfies the interface we are after
        # NOTE: a solution probably entails a better understanding of how
        # the underlying interface is used across this repo
        return self

    async def write(self, data: bytes) -> None:
        # TODO Write `data` with authenticated encryption
        raise NotImplementedError

    async def read(self) -> bytes:
        # TODO Read data after verifying it
        raise NotImplementedError


class SecIOTransport(BaseSecureTransport):
    """
    ``SecIOTransport`` upgrades a ``IRawConnection`` connection to provide
    authenticated encryption via the `secio` protocol.
    """

    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are not the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        return await SecIOSession(self, conn, ID(b""))

    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
        return await SecIOSession(self, conn, peer_id)
