from collections.abc import Sequence

from libp2p.peer.id import ID

from .pb import rpc_pb2


class CacheEntry:
    mid: str
    topics: list[str]

    """
    A logical representation of an entry in the mcache's _history_.
    """

    def __init__(self, mid: str, topics: Sequence[str]) -> None:
        """
        Constructor.

        :param mid: The message ID, a combination of (seqno, from_id).
        :param topics: The list of topics this message was sent on.
        """
        self.mid = mid
        self.topics = list(topics)


class MessageCache:
    window_size: int
    history_size: int

    msgs: dict[str, rpc_pb2.Message]
    history: list[list[CacheEntry]]

    def __init__(self, window_size: int, history_size: int) -> None:
        """
        Constructor.

        :param window_size: Size of the window desired.
        :param history_size: Size of the history desired.
        """
        self.window_size = window_size
        self.history_size = history_size

        # str mid -> rpc message
        self.msgs = dict()

        # max length of history_size. each item is a list of CacheEntry.
        # messages lost upon shift().
        self.history = [[] for _ in range(history_size)]

    def put(self, msg: rpc_pb2.Message) -> None:
        """
        Put a message into the mcache.

        :param msg: The rpc message to put in. Should contain seqno and from_id
        """
        mid: str = self.parse_mid(msg.seqno, msg.from_id)
        self.msgs[mid] = msg

        self.history[0].append(CacheEntry(mid, msg.topicIDs))

    def get(self, mid: str) -> rpc_pb2.Message | None:
        """
        Get a message from the mcache.

        :param mid: The message ID (a combination of seqno and from_id).
        :return: The rpc message associated with this message ID, or None if not found.
        """
        return self.msgs.get(mid, None)

    def window(self, topic: str) -> list[str]:
        """
        Get the window for this topic.

        :param topic: The topic whose message IDs are desired.
        :return: List of message IDs (mids) in the current window for the topic.
        """
        mids: list[str] = []

        for entries_list in self.history[: self.window_size]:
            for entry in entries_list:
                if topic in entry.topics:
                    mids.append(entry.mid)

        return mids

    def shift(self) -> None:
        """
        Shift the window over by 1 position, dropping the last element of the history.
        """
        last_entries: list[CacheEntry] = self.history[len(self.history) - 1]

        for entry in last_entries:
            self.msgs.pop(entry.mid)

        i: int = len(self.history) - 2

        while i >= 0:
            self.history[i + 1] = self.history[i]
            i -= 1

        self.history[0] = []

    def parse_mid(self, seqno: bytes, from_id: bytes) -> str:
        """
        Create a message ID by concatenating seqno and from_id.

        :param seqno: Sequence number as bytes.
        :param from_id: Sender's ID as bytes.
        :return: String concatenation of seqno and from_id.
        """
        seqno_int = int.from_bytes(seqno, "big")
        from_id_str = str(ID(from_id))
        return str(seqno_int) + from_id_str
