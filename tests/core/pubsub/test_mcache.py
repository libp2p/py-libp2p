from collections.abc import (
    Sequence,
)

from libp2p.peer.id import (
    ID,
)
from libp2p.pubsub.mcache import (
    MessageCache,
)
from libp2p.pubsub.pb import (
    rpc_pb2,
)


def make_msg(
    topic_ids: Sequence[str],
    seqno: bytes,
    from_id: ID,
) -> rpc_pb2.Message:
    return rpc_pb2.Message(
        from_id=from_id.to_bytes(), seqno=seqno, topicIDs=list(topic_ids)
    )


def test_mcache():
    # Ported from:
    # https://github.com/libp2p/go-libp2p-pubsub/blob/51b7501433411b5096cac2b4994a36a68515fc03/mcache_test.go
    mcache = MessageCache(3, 5)
    msgs = []

    for i in range(60):
        msgs.append(make_msg(["test"], i.to_bytes(1, "big"), ID(b"test")))

    for i in range(10):
        mcache.put(msgs[i])

    for i in range(10):
        msg = msgs[i]
        mid = msg.from_id + msg.seqno
        get_msg = mcache.get(mid)

        # successful read
        assert get_msg == msg

    gids = mcache.window("test")

    assert len(gids) == 10

    for i in range(10):
        msg = msgs[i]
        mid = msg.from_id + msg.seqno

        assert mid == gids[i]

    mcache.shift()

    for i in range(10, 20):
        mcache.put(msgs[i])

    for i in range(20):
        msg = msgs[i]
        mid = msg.from_id + msg.seqno
        get_msg = mcache.get(mid)

        assert get_msg == msg

    gids = mcache.window("test")

    assert len(gids) == 20

    for i in range(10):
        msg = msgs[i]
        mid = msg.from_id + msg.seqno

        assert mid == gids[10 + i]

    for i in range(10, 20):
        msg = msgs[i]
        mid = msg.from_id + msg.seqno

        assert mid == gids[i - 10]

    mcache.shift()

    for i in range(20, 30):
        mcache.put(msgs[i])

    mcache.shift()

    for i in range(30, 40):
        mcache.put(msgs[i])

    mcache.shift()

    for i in range(40, 50):
        mcache.put(msgs[i])

    mcache.shift()

    for i in range(50, 60):
        mcache.put(msgs[i])

    assert len(mcache.msgs) == 50

    for i in range(10):
        msg = msgs[i]
        mid = msg.from_id + msg.seqno
        get_msg = mcache.get(mid)

        # Should be evicted from cache
        assert not get_msg

    for i in range(10, 60):
        msg = msgs[i]
        mid = msg.from_id + msg.seqno
        get_msg = mcache.get(mid)

        assert get_msg == msg

    gids = mcache.window("test")

    assert len(gids) == 30

    for i in range(10):
        msg = msgs[50 + i]
        mid = msg.from_id + msg.seqno

        assert mid == gids[i]

    for i in range(10, 20):
        msg = msgs[30 + i]
        mid = msg.from_id + msg.seqno

        assert mid == gids[i]

    for i in range(20, 30):
        msg = msgs[10 + i]
        mid = msg.from_id + msg.seqno

        assert mid == gids[i]


# ---------------------------------------------------------------------------
# Additional tests covering the deque-based optimization (issue #1333)
# ---------------------------------------------------------------------------


def _make_mid(peer: bytes, seq: int) -> bytes:
    return peer + seq.to_bytes(2, "big")


def _make_raw_msg(topics: list[str], peer: bytes, seq: int) -> rpc_pb2.Message:
    return rpc_pb2.Message(from_id=peer, seqno=seq.to_bytes(2, "big"), topicIDs=topics)


def test_window_returns_newest_slot_first() -> None:
    """Newest slot must appear at the front of the window result."""
    mc = MessageCache(window_size=2, history_size=4)
    old_msg = _make_raw_msg(["t"], b"p", 1)
    mc.put(old_msg)
    mc.shift()
    new_msg = _make_raw_msg(["t"], b"p", 2)
    mc.put(new_msg)

    gids = mc.window("t")
    assert len(gids) == 2
    assert gids[0] == _make_mid(b"p", 2)   # newest first
    assert gids[1] == _make_mid(b"p", 1)   # older second


def test_window_unknown_topic_returns_empty() -> None:
    """window() on a topic with no messages must return [] without error."""
    mc = MessageCache(window_size=3, history_size=5)
    mc.put(_make_raw_msg(["alpha"], b"p", 1))
    assert mc.window("beta") == []


def test_window_respects_window_size_not_history_size() -> None:
    """window() must stop at window_size, not history_size."""
    mc = MessageCache(window_size=2, history_size=5)
    for slot in range(5):
        mc.put(_make_raw_msg(["t"], b"p", slot))
        mc.shift()
    # Only the 2 most-recent slots fall inside the window — but we just
    # shifted 5 times with 1 msg each, so only msgs from slots 3 and 4
    # (history[-1] is oldest, which has been evicted from history_size=5
    # after 5 shifts).  The window covers the 2 newest non-empty slots.
    gids = mc.window("t")
    assert len(gids) <= 2


def test_shift_evicts_only_oldest_slot() -> None:
    """After one shift, exactly the oldest slot's messages are removed."""
    mc = MessageCache(window_size=2, history_size=3)
    # slot 0: msgs 1-3
    for i in range(1, 4):
        mc.put(_make_raw_msg(["t"], b"p", i))
    mc.shift()
    # slot 0 (new): msgs 4-6
    for i in range(4, 7):
        mc.put(_make_raw_msg(["t"], b"p", i))
    mc.shift()
    # slot 0 (new): msgs 7-9
    for i in range(7, 10):
        mc.put(_make_raw_msg(["t"], b"p", i))
    mc.shift()
    # history_size=3 → after 3 shifts, slot with msgs 1-3 is evicted
    for i in range(1, 4):
        assert mc.get(_make_mid(b"p", i)) is None
    for i in range(4, 10):
        assert mc.get(_make_mid(b"p", i)) is not None


def test_full_history_cycle_clears_all_msgs() -> None:
    """Shifting through the entire history must empty msgs completely."""
    history_size = 5
    mc = MessageCache(window_size=2, history_size=history_size)
    for i in range(10):
        mc.put(_make_raw_msg(["t"], b"p", i))
    for _ in range(history_size):
        mc.shift()
    assert len(mc.msgs) == 0


def test_topic_index_invariant_after_puts_and_shifts() -> None:
    """_topic_index must mirror history at every step."""
    mc = MessageCache(window_size=3, history_size=5)
    mc.put(_make_raw_msg(["x"], b"p", 1))
    mc.put(_make_raw_msg(["y"], b"p", 2))

    assert _make_mid(b"p", 1) in mc._topic_index[0].get("x", [])
    assert _make_mid(b"p", 2) in mc._topic_index[0].get("y", [])

    mc.shift()
    # After shift, slot 0 is fresh; old slot moves to index 1
    assert mc._topic_index[0] == {}
    assert _make_mid(b"p", 1) in mc._topic_index[1].get("x", [])


def test_multi_topic_message_appears_in_all_windows() -> None:
    """A message published to N topics must appear in each topic's window."""
    mc = MessageCache(window_size=3, history_size=5)
    topics = ["alpha", "beta", "gamma"]
    mc.put(_make_raw_msg(topics, b"p", 1))
    mid = _make_mid(b"p", 1)

    for topic in topics:
        assert mid in mc.window(topic), f"mid missing from window({topic!r})"


def test_shift_with_large_history_size() -> None:
    """O(1) shift must work correctly regardless of history_size."""
    history_size = 120   # high-throughput node scenario
    mc = MessageCache(window_size=6, history_size=history_size)
    for i in range(history_size):
        mc.put(_make_raw_msg(["t"], b"p", i))
        mc.shift()
    # All messages should be evicted after shifting through the full history
    assert len(mc.msgs) == 0


def test_window_with_many_topics() -> None:
    """window() must scale to a large number of topics without scanning."""
    mc = MessageCache(window_size=3, history_size=5)
    topics = [f"topic-{i}" for i in range(50)]
    for idx, topic in enumerate(topics):
        mc.put(_make_raw_msg([topic], b"p", idx))

    for idx, topic in enumerate(topics):
        gids = mc.window(topic)
        assert len(gids) == 1
        assert gids[0] == _make_mid(b"p", idx)


def test_history_type_is_deque() -> None:
    """history must be a collections.deque (not a plain list)."""
    from collections import deque

    mc = MessageCache(window_size=3, history_size=5)
    assert isinstance(mc.history, deque)
    assert mc.history.maxlen == 5
