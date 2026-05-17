from collections import deque
from collections.abc import (
    Sequence,
)

from .pb import (
    rpc_pb2,
)


def default_msg_id_fn(msg: rpc_pb2.Message) -> bytes:
    """
    Compute the default message ID matching go-libp2p's DefaultMsgIdFn.

    Ref: https://github.com/libp2p/go-libp2p-pubsub/blob/master/pubsub.go#L1327-L1330

    :param msg: The protobuf message.
    :return: ``from_id + seqno`` concatenated as bytes.
    """
    return msg.from_id + msg.seqno


class CacheEntry:
    mid: bytes
    topics: list[str]

    """
    A logical representation of an entry in the mcache's _history_.
    """

    def __init__(self, mid: bytes, topics: Sequence[str]) -> None:
        """
        Constructor.

        :param mid: message ID as bytes (from_id + seqno)
        :param topics: list of topics this message was sent on
        """
        self.mid = mid
        self.topics = list(topics)


class MessageCache:
    window_size: int
    history_size: int

    msgs: dict[bytes, rpc_pb2.Message]

    # deque(maxlen=history_size) gives O(1) slot rotation via appendleft,
    # replacing the previous O(history_size) manual list shift.
    history: deque[list[CacheEntry]]

    # Parallel topic index: one dict[topic, list[mid]] per history slot.
    # Lets window(topic) resolve in O(window_size + results) instead of the
    # previous O(window_size × entries_per_slot × topics_per_message).
    _topic_index: deque[dict[str, list[bytes]]]

    def __init__(self, window_size: int, history_size: int) -> None:
        """
        Constructor.

        :param window_size: Size of the window desired.
        :param history_size: Size of the history desired.
        :return: the MessageCache
        """
        self.window_size = window_size
        self.history_size = history_size

        # msg_id (from_id + seqno) -> rpc message
        self.msgs = dict()

        # maxlen ensures appendleft() auto-drops the oldest slot — O(1) rotation.
        self.history = deque(
            [[] for _ in range(history_size)], maxlen=history_size
        )
        self._topic_index = deque(
            [{} for _ in range(history_size)], maxlen=history_size
        )

    def put(self, msg: rpc_pb2.Message) -> None:
        """
        Put a message into the mcache.

        :param msg: The rpc message to put in. Should contain seqno and from_id
        """
        mid: bytes = default_msg_id_fn(msg)
        if mid in self.msgs:
            return
        self.msgs[mid] = msg

        self.history[0].append(CacheEntry(mid, msg.topicIDs))

        # Keep _topic_index in sync so window() never scans CacheEntry lists.
        slot = self._topic_index[0]
        for topic in msg.topicIDs:
            if topic not in slot:
                slot[topic] = []
            slot[topic].append(mid)

    def get(self, mid: bytes) -> rpc_pb2.Message | None:
        """
        Get a message from the mcache.

        :param mid: message ID as bytes (from_id + seqno).
        :return: The rpc message associated with this mid
        """
        return self.msgs.get(mid)

    def window(self, topic: str) -> list[bytes]:
        """
        Get the message IDs in the gossip window for *topic*.

        Complexity: O(window_size + results) via topic index.
        Previous complexity was O(window_size × entries_per_slot × topics_per_message).

        :param topic: Topic whose message ids we desire.
        :return: List of mids in the current window, newest slot first.
        """
        mids: list[bytes] = []
        for i, slot in enumerate(self._topic_index):
            if i >= self.window_size:
                break
            topic_mids = slot.get(topic)
            if topic_mids:
                mids.extend(topic_mids)
        return mids

    def shift(self) -> None:
        """
        Shift the window forward by one slot, evicting the oldest slot.

        Complexity: O(evicted_messages).
        Previous complexity was O(history_size) due to manual list rotation.
        """
        # Evict messages that are about to be dropped from the oldest slot.
        for entry in self.history[-1]:
            self.msgs.pop(entry.mid, None)

        # appendleft pushes a fresh empty slot to the front; because both
        # deques have maxlen=history_size, the oldest slot is dropped in O(1).
        self.history.appendleft([])
        self._topic_index.appendleft({})
