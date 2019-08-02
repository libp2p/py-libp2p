from typing import Dict, List, Optional, Sequence, Tuple

from .pb import rpc_pb2


class CacheEntry:

    mid: Tuple[bytes, bytes]
    topics: List[str]

    """
    A logical representation of an entry in the mcache's _history_.
    """

    def __init__(self, mid: Tuple[bytes, bytes], topics: Sequence[str]) -> None:
        """
        Constructor.
        :param mid: (seqno, from_id) of the msg
        :param topics: list of topics this message was sent on
        """
        self.mid = mid
        self.topics = list(topics)


class MessageCache:

    window_size: int
    history_size: int

    msgs: Dict[Tuple[bytes, bytes], rpc_pb2.Message]

    history: List[List[CacheEntry]]

    def __init__(self, window_size: int, history_size: int) -> None:
        """
        Constructor.
        :param window_size: Size of the window desired.
        :param history_size: Size of the history desired.
        :return: the MessageCache
        """
        self.window_size = window_size
        self.history_size = history_size

        # (seqno, from_id) -> rpc message
        self.msgs = dict()

        # max length of history_size. each item is a list of CacheEntry.
        # messages lost upon shift().
        self.history = [[] for _ in range(history_size)]

    def put(self, msg: rpc_pb2.Message) -> None:
        """
        Put a message into the mcache.
        :param msg: The rpc message to put in. Should contain seqno and from_id
        """
        mid: Tuple[bytes, bytes] = (msg.seqno, msg.from_id)
        self.msgs[mid] = msg

        self.history[0].append(CacheEntry(mid, msg.topicIDs))

    def get(self, mid: Tuple[bytes, bytes]) -> Optional[rpc_pb2.Message]:
        """
        Get a message from the mcache.
        :param mid: (seqno, from_id) of the message to get.
        :return: The rpc message associated with this mid
        """
        if mid in self.msgs:
            return self.msgs[mid]

        return None

    def window(self, topic: str) -> List[Tuple[bytes, bytes]]:
        """
        Get the window for this topic.
        :param topic: Topic whose message ids we desire.
        :return: List of mids in the current window.
        """
        mids: List[Tuple[bytes, bytes]] = []

        for entries_list in self.history[: self.window_size]:
            for entry in entries_list:
                for entry_topic in entry.topics:
                    if entry_topic == topic:
                        mids.append(entry.mid)

        return mids

    def shift(self) -> None:
        """
        Shift the window over by 1 position, dropping the last element of the history.
        """
        last_entries: List[CacheEntry] = self.history[len(self.history) - 1]

        for entry in last_entries:
            del self.msgs[entry.mid]

        i: int = len(self.history) - 2

        while i >= 0:
            self.history[i + 1] = self.history[i]
            i -= 1

        self.history[0] = []
