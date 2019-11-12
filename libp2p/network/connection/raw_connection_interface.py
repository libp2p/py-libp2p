from libp2p.io.abc import ReadWriteCloser


class IRawConnection(ReadWriteCloser):
    """A Raw Connection provides a Reader and a Writer."""

    is_initiator: bool
