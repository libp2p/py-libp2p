from abc import ABC, abstractmethod

class IMultiselectClient(ABC):

    @abstractmethod
    def select_proto_or_fail(self, protocol, stream):
        """
        Send message to multiselect selecting protocol
        and fail if multiselect does not return same protocol
        :param protocol: protocol to select
        :param stream: stream to communicate with multiselect over
        :return: selected protocol
        """

    @abstractmethod
    def select_one_of(self, protocols, stream):
        """
        For each protocol, send message to multiselect selecting protocol
        and fail if multiselect does not return same protocol. Returns first
        protocol that multiselect agrees on (i.e. that multiselect selects)
        :param protocol: protocol to select
        :param stream: stream to communicate with multiselect over
        :return: selected protocol
        """
