from abc import (
    ABC,
    abstractmethod,
)

import trio

from libp2p.io.abc import (
    ReadWriteCloser,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.security.secure_conn_interface import (
    ISecureConn,
)


class IMuxedConn(ABC):
    """
    reference: https://github.com/libp2p/go-stream-muxer/blob/master/muxer.go
    """

    peer_id: ID
    event_started: trio.Event

    @abstractmethod
    def __init__(self, conn: ISecureConn, peer_id: ID) -> None:
        """
        Create a new muxed connection.

        :param conn: an instance of secured connection
        for new muxed streams
        :param peer_id: peer_id of peer the connection is to
        """

    @property
    @abstractmethod
    def is_initiator(self) -> bool:
        """If this connection is the initiator."""

    @abstractmethod
    async def start(self) -> None:
        """Start the multiplexer."""

    @abstractmethod
    async def close(self) -> None:
        """Close connection."""

    @property
    @abstractmethod
    def is_closed(self) -> bool:
        """
        Check connection is fully closed.

        :return: true if successful
        """

    @abstractmethod
    async def open_stream(self) -> "IMuxedStream":
        """
        Create a new muxed_stream.

        :return: a new ``IMuxedStream`` stream
        """

    @abstractmethod
    async def accept_stream(self) -> "IMuxedStream":
        """Accept a muxed stream opened by the other end."""


class IMuxedStream(ReadWriteCloser):
    muxed_conn: IMuxedConn

    @abstractmethod
    async def reset(self) -> None:
        """Close both ends of the stream tells this remote side to hang up."""

    @abstractmethod
    def set_deadline(self, ttl: int) -> bool:
        """
        Set deadline for muxed stream.

        :return: a new stream
        """
