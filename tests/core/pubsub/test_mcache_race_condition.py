"""
Test for MessageCache duplicate handling (issue #1118).

When async validators process the same message concurrently, put() can be
called multiple times for the same mid. Without protection, this creates
duplicate history entries, causing KeyError in shift().
"""

from libp2p.pubsub.mcache import MessageCache
from libp2p.pubsub.pb import rpc_pb2


def make_msg(seqno: bytes, from_id: bytes) -> rpc_pb2.Message:
    return rpc_pb2.Message(from_id=from_id, seqno=seqno, topicIDs=["test"])


def test_put_rejects_duplicates():
    """Duplicate put() calls must not create duplicate history entries."""
    mcache = MessageCache(window_size=3, history_size=5)

    msg1 = make_msg(b"\x01", b"peer1")
    msg2 = make_msg(b"\x02", b"peer1")

    # Simulate race: same messages put multiple times
    mcache.put(msg1)
    mcache.put(msg1)
    mcache.put(msg2)
    mcache.put(msg1)
    mcache.put(msg2)

    # Should have exactly 2 unique messages in msgs dict
    assert len(mcache.msgs) == 2

    # Should have exactly 1 history entry per unique message
    history_mids = [e.mid for entries in mcache.history for e in entries]
    assert history_mids.count((msg1.seqno, msg1.from_id)) == 1
    assert history_mids.count((msg2.seqno, msg2.from_id)) == 1


def test_shift_handles_duplicates():
    """shift() must not raise KeyError after duplicate puts."""
    mcache = MessageCache(window_size=3, history_size=5)

    msg = make_msg(b"\x01", b"peer1")

    mcache.put(msg)
    mcache.put(msg)

    # Shift through entire history - must not raise KeyError
    for _ in range(mcache.history_size):
        mcache.shift()

    assert len(mcache.msgs) == 0


def test_duplicate_put_keeps_first_topics():
    """When same mid is put with different topicIDs, first one wins."""
    mcache = MessageCache(window_size=3, history_size=5)

    # Create two messages with the same mid but different topics
    msg_first = rpc_pb2.Message(from_id=b"peer1", seqno=b"\x01", topicIDs=["topic-A"])
    msg_second = rpc_pb2.Message(
        from_id=b"peer1", seqno=b"\x01", topicIDs=["topic-A", "topic-B"]
    )  # duplicate mid

    mcache.put(msg_first)
    mcache.put(msg_second)  # This will be ignored due to duplicate mid

    mid = (b"\x01", b"peer1")

    # First message's topics are preserved
    window_a = mcache.window("topic-A")
    assert mid in window_a

    window_b = mcache.window("topic-B")
    assert mid not in window_b  # Not present from the second (ignored) put
