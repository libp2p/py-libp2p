from abc import ABC, abstractmethod


class IHost(ABC):

    @abstractmethod
    def get_id(self):
        """
        :return: peer_id of host
        """

    @abstractmethod
    def get_network(self):
        """
        :return: network instance of host
        """

    @abstractmethod
    def get_mux(self):
        """
        :return: mux instance of host
        """

    @abstractmethod
    def get_addrs(self):
        """
        :return: all the multiaddr addresses this host is listening too
        """

    @abstractmethod
    def set_stream_handler(self, protocol_id, stream_handler):
        """
        set stream handler for host
        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler function
        :return: true if successful
        """

    # protocol_id can be a list of protocol_ids
    # stream will decide which protocol_id to run on
    @abstractmethod
    def new_stream(self, peer_id, protocol_ids):
        """
        :param peer_id: peer_id that host is connecting
        :param protocol_ids: protocol ids that stream can run on
        :return: true if successful
        """

    @abstractmethod
    def connect(self, peer_info):
        """
        connect ensures there is a connection between this host and the peer with
        given peer_info.peer_id. connect will absorb the addresses in peer_info into its internal
        peerstore. If there is not an active connection, connect will issue a
        dial, and block until a connection is open, or an error is
        returned.

        :param peer_info: peer_info of the host we want to connect to
        :type peer_info: peer.peerinfo.PeerInfo
        """
