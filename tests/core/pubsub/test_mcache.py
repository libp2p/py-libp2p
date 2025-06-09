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
        mid = (msg.seqno, msg.from_id)
        get_msg = mcache.get(mid)

        # successful read
        assert get_msg == msg

    gids = mcache.window("test")

    assert len(gids) == 10

    for i in range(10):
        msg = msgs[i]
        mid = (msg.seqno, msg.from_id)

        assert mid == gids[i]

    mcache.shift()

    for i in range(10, 20):
        mcache.put(msgs[i])

    for i in range(20):
        msg = msgs[i]
        mid = (msg.seqno, msg.from_id)
        get_msg = mcache.get(mid)

        assert get_msg == msg

    gids = mcache.window("test")

    assert len(gids) == 20

    for i in range(10):
        msg = msgs[i]
        mid = (msg.seqno, msg.from_id)

        assert mid == gids[10 + i]

    for i in range(10, 20):
        msg = msgs[i]
        mid = (msg.seqno, msg.from_id)

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
        mid = (msg.seqno, msg.from_id)
        get_msg = mcache.get(mid)

        # Should be evicted from cache
        assert not get_msg

    for i in range(10, 60):
        msg = msgs[i]
        mid = (msg.seqno, msg.from_id)
        get_msg = mcache.get(mid)

        assert get_msg == msg

    gids = mcache.window("test")

    assert len(gids) == 30

    for i in range(10):
        msg = msgs[50 + i]
        mid = (msg.seqno, msg.from_id)

        assert mid == gids[i]

    for i in range(10, 20):
        msg = msgs[30 + i]
        mid = (msg.seqno, msg.from_id)

        assert mid == gids[i]

    for i in range(20, 30):
        msg = msgs[10 + i]
        mid = (msg.seqno, msg.from_id)

        assert mid == gids[i]
