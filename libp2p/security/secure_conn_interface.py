from abc import ABC, abstractmethod

from libp2p.crypto.keys import PrivateKey, PublicKey
from libp2p.network.connection.raw_connection_interface import IRawConnection
from libp2p.peer.id import ID


"""
Represents a secured connection object, which includes a connection and details about the security
involved in the secured connection

Relevant go repo: https://github.com/libp2p/go-conn-security/blob/master/interface.go
"""


class AbstractSecureConn(ABC):
    @abstractmethod
    def get_local_peer(self) -> ID:
        pass

    @abstractmethod
    def get_local_private_key(self) -> PrivateKey:
        pass

    @abstractmethod
    def get_remote_peer(self) -> ID:
        pass

    @abstractmethod
    def get_remote_public_key(self) -> PublicKey:
        pass


class ISecureConn(AbstractSecureConn, IRawConnection):
    pass
