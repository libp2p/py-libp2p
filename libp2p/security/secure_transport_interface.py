from abc import ABC, abstractmethod

from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID
from libp2p.security.secure_conn_interface import ISecureConn


"""
Transport that is used to secure a connection. This transport is
chosen by a security transport multistream module.

Relevant go repo: https://github.com/libp2p/go-conn-security/blob/master/interface.go
"""


class ISecureTransport(ABC):
    @abstractmethod
    async def secure_inbound(self, conn: IRawConnection) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are not the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """

    @abstractmethod
    async def secure_outbound(self, conn: IRawConnection, peer_id: ID) -> ISecureConn:
        """
        Secure the connection, either locally or by communicating with opposing node via conn,
        for an inbound connection (i.e. we are the initiator)
        :return: secure connection object (that implements secure_conn_interface)
        """
