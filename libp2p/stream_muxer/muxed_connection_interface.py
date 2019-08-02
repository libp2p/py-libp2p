from abc import ABC, abstractmethod

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiaddr import Multiaddr
    from libp2p.security.secure_conn_interface import ISecureConn
    from libp2p.network.swarm import GenericProtocolHandlerFn
    from libp2p.peer.id import ID
    from libp2p.stream_muxer.muxed_stream_interface import IMuxedStream


class IMuxedConn(ABC):
    """
    reference: https://github.com/libp2p/go-stream-muxer/blob/master/muxer.go
    """

    initiator: bool
    peer_id: "ID"

    @abstractmethod
    def __init__(
        self,
        conn: "ISecureConn",
        generic_protocol_handler: "GenericProtocolHandlerFn",
        peer_id: "ID",
    ) -> None:
        """
        create a new muxed connection
        :param conn: an instance of secured connection
        :param generic_protocol_handler: generic protocol handler
        for new muxed streams
        :param peer_id: peer_id of peer the connection is to
        """

    @abstractmethod
    def close(self) -> None:
        """
        close connection
        """

    @abstractmethod
    def is_closed(self) -> bool:
        """
        check connection is fully closed
        :return: true if successful
        """

    @abstractmethod
    async def open_stream(
        self, protocol_id: str, multi_addr: "Multiaddr"
    ) -> "IMuxedStream":
        """
        creates a new muxed_stream
        :param protocol_id: protocol_id of stream
        :param multi_addr: multi_addr that stream connects to
        :return: a new stream
        """

    @abstractmethod
    async def accept_stream(self) -> None:
        """
        accepts a muxed stream opened by the other end
        """
