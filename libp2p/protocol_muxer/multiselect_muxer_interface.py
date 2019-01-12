from abc import ABC, abstractmethod


class IMultiselectMuxer(ABC):
    """
    Multiselect module that is responsible for responding to
    a multiselect client and deciding on
    a specific protocol and handler pair to use for communication
    """

    @abstractmethod
    def add_handler(self, protocol, handler):
        """
        Store the handler with the given protocol
        :param protocol: protocol name
        :param handler: handler function
        """

    @abstractmethod
    def negotiate(self, stream):
        """
        Negotiate performs protocol selection
        :param stream: stream to negotiate on
        :return: selected protocol name, handler function
        :raise Exception: negotiation failed exception
        """
