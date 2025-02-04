from collections.abc import (
    Sequence,
)

from libp2p.abc import (
    IHost,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.pubsub.pb import (
    rpc_pb2,
)
from libp2p.tools.utils import (
    connect,
)


def make_pubsub_msg(
    origin_id: ID, topic_ids: Sequence[str], data: bytes, seqno: bytes
) -> rpc_pb2.Message:
    return rpc_pb2.Message(
        from_id=origin_id.to_bytes(), seqno=seqno, data=data, topicIDs=list(topic_ids)
    )


# TODO: Implement sparse connect
async def dense_connect(hosts: Sequence[IHost]) -> None:
    await connect_some(hosts, 10)


# FIXME: `degree` is not used at all
async def connect_some(hosts: Sequence[IHost], degree: int) -> None:
    for i, host in enumerate(hosts):
        for host2 in hosts[i + 1 :]:
            await connect(host, host2)


async def one_to_all_connect(hosts: Sequence[IHost], central_host_index: int) -> None:
    for i, host in enumerate(hosts):
        if i != central_host_index:
            await connect(hosts[central_host_index], host)
