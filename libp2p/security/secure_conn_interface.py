from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from libp2p.network.connection.raw_connection_interface import IRawConnection
    from .typing import TSecurityDetails


"""
Represents a secured connection object, which includes a connection and details about the security
involved in the secured connection

Relevant go repo: https://github.com/libp2p/go-conn-security/blob/master/interface.go
"""


class ISecureConn(ABC):
    @abstractmethod
    def get_conn(self) -> "IRawConnection":
        """
        :return: the underlying raw connection
        """

    @abstractmethod
    def get_security_details(self) -> "TSecurityDetails":
        """
        :return: map containing details about the connections security
        """
