from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from libp2p.io.abc import ReadWriteCloser
from libp2p.peer.id import ID
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.stream_muxer.mplex.constants import HeaderTags
from libp2p.stream_muxer.mplex.datastructures import StreamID

if TYPE_CHECKING:
    # Prevent GenericProtocolHandlerFn introducing circular dependencies
    from libp2p.network.typing import GenericProtocolHandlerFn  # noqa: F401


class IMuxedConn(ABC):
    """
    reference: https://github.com/libp2p/go-stream-muxer/blob/master/muxer.go
    """

    peer_id: ID

    @abstractmethod
    def __init__(
        self,
        conn: ISecureConn,
        generic_protocol_handler: "GenericProtocolHandlerFn",
        peer_id: ID,
    ) -> None:
        """
        create a new muxed connection
        :param conn: an instance of secured connection
        :param generic_protocol_handler: generic protocol handler
        for new muxed streams
        :param peer_id: peer_id of peer the connection is to
        """

    @property
    @abstractmethod
    def initiator(self) -> bool:
        pass

    @abstractmethod
    async def close(self) -> None:
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
    async def open_stream(self) -> "IMuxedStream":
        """
        creates a new muxed_stream
        :return: a new ``IMuxedStream`` stream
        """

    @abstractmethod
    async def accept_stream(self, stream_id: StreamID, name: str) -> None:
        """
        accepts a muxed stream opened by the other end
        """

    @abstractmethod
    async def send_message(
        self, flag: HeaderTags, data: bytes, stream_id: StreamID
    ) -> int:
        """
        sends a message over the connection
        :param header: header to use
        :param data: data to send in the message
        :param stream_id: stream the message is in
        """


class IMuxedStream(ReadWriteCloser):

    mplex_conn: IMuxedConn

    @abstractmethod
    async def reset(self) -> None:
        """
        closes both ends of the stream
        tells this remote side to hang up
        """

    @abstractmethod
    def set_deadline(self, ttl: int) -> bool:
        """
        set deadline for muxed stream
        :return: a new stream
        """
