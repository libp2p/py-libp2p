import pytest
from libp2p.pubsub.mcache import MessageCache


class Msg:

    def __init__(self, topicIDs, seqno, from_id):
        self.topicIDs = topicIDs
        self.seqno = seqno,
        self.from_id = from_id

@pytest.mark.asyncio
async def test_mcache():
    mcache = MessageCache(3, 5)
    msgs = []

    for i in range(60):
        msgs.append(Msg(["test"], i, "test"))

    for i in range(10):
        mcache.put(msgs[i])

    for i in range(10):
        msg = msgs[i]
        mid = (msg.seqno, msg.from_id)
        get_msg = mcache.get(mid)

        # successful read
        assert get_msg

    gids = mcache.window('test')

    assert len(gids) == 10

    for i in range(10):
        msg = msgs[i]
        mid = (msg.seqno, msg.from_id)

        assert mid == gids[i]
