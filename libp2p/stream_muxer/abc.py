from abc import ABC, abstractmethod

from libp2p.io.abc import ReadWriteCloser
from libp2p.peer.id import ID
from libp2p.security.secure_conn_interface import ISecureConn


class IMuxedConn(ABC):
    """
    reference: https://github.com/libp2p/go-stream-muxer/blob/master/muxer.go
    """

    peer_id: ID

    @abstractmethod
    def __init__(self, conn: ISecureConn, peer_id: ID) -> None:
        """
        create a new muxed connection.

        :param conn: an instance of secured connection
        for new muxed streams
        :param peer_id: peer_id of peer the connection is to
        """

    @property
    @abstractmethod
    def is_initiator(self) -> bool:
        pass

    @abstractmethod
    async def close(self) -> None:
        """close connection."""

    @abstractmethod
    def is_closed(self) -> bool:
        """
        check connection is fully closed.

        :return: true if successful
        """

    @abstractmethod
    async def open_stream(self) -> "IMuxedStream":
        """
        creates a new muxed_stream.

        :return: a new ``IMuxedStream`` stream
        """

    @abstractmethod
    async def accept_stream(self) -> "IMuxedStream":
        """accepts a muxed stream opened by the other end."""


class IMuxedStream(ReadWriteCloser):

    muxed_conn: IMuxedConn

    @abstractmethod
    async def reset(self) -> None:
        """closes both ends of the stream tells this remote side to hang up."""

    @abstractmethod
    def set_deadline(self, ttl: int) -> bool:
        """
        set deadline for muxed stream.

        :return: a new stream
        """
