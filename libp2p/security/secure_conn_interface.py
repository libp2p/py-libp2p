from abc import ABC, abstractmethod

"""
Represents a secured connection object, which includes a connection and details about the security
involved in the secured connection

Relevant go repo: https://github.com/libp2p/go-conn-security/blob/master/interface.go
"""
class ISecureConn(ABC):

    @abstractmethod
    def get_conn(self):
        """
        :return: connection object that has been made secure
        """

    @abstractmethod
    def get_security_details(self):
        """
        :return: map containing details about the connections security
        """

