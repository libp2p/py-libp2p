from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from libp2p.peer.id import ID
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.stream_muxer.mplex.constants import HeaderTags

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
    async def read_buffer(self, stream_id: int) -> bytes:
        """
        Read a message from stream_id's buffer, check raw connection for new messages
        :param stream_id: stream id of stream to read from
        :return: message read
        """

    @abstractmethod
    async def read_buffer_nonblocking(self, stream_id: int) -> Optional[bytes]:
        """
        Read a message from `stream_id`'s buffer, non-blockingly.
        """

    @abstractmethod
    async def open_stream(self) -> "IMuxedStream":
        """
        creates a new muxed_stream
        :return: a new ``IMuxedStream`` stream
        """

    @abstractmethod
    async def accept_stream(self, name: str) -> None:
        """
        accepts a muxed stream opened by the other end
        """

    @abstractmethod
    async def send_message(self, flag: HeaderTags, data: bytes, stream_id: int) -> int:
        """
        sends a message over the connection
        :param header: header to use
        :param data: data to send in the message
        :param stream_id: stream the message is in
        """


class IMuxedStream(ABC):

    mplex_conn: IMuxedConn

    @abstractmethod
    async def read(self, n: int = -1) -> bytes:
        """
        reads from the underlying muxed_conn
        :param n: number of bytes to read
        :return: bytes of input
        """

    @abstractmethod
    async def write(self, data: bytes) -> int:
        """
        writes to the underlying muxed_conn
        :return: number of bytes written
        """

    @abstractmethod
    async def close(self) -> bool:
        """
        close the underlying muxed_conn
        :return: true if successful
        """

    @abstractmethod
    async def reset(self) -> bool:
        """
        closes both ends of the stream
        tells this remote side to hang up
        :return: true if successful
        """

    @abstractmethod
    def set_deadline(self, ttl: int) -> bool:
        """
        set deadline for muxed stream
        :return: a new stream
        """
