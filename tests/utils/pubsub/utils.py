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


async def dense_connect(hosts: Sequence[IHost]) -> None:
    await connect_some(hosts, 10)


async def connect_some(hosts: Sequence[IHost], degree: int) -> None:
    """
    Connect each host to up to 'degree' number of other hosts.
    Creates a sparse network topology where each node has limited connections.
    """
    for i, host in enumerate(hosts):
        connections_made = 0
        for j in range(i + 1, len(hosts)):
            if connections_made >= degree:
                break
            await connect(host, hosts[j])
            connections_made += 1


async def one_to_all_connect(hosts: Sequence[IHost], central_host_index: int) -> None:
    for i, host in enumerate(hosts):
        if i != central_host_index:
            await connect(hosts[central_host_index], host)


async def sparse_connect(hosts: Sequence[IHost], degree: int = 3) -> None:
    """
    Create a sparse network topology where each node connects to a limited number of
    other nodes. This is more efficient than dense connect for large networks.

    The function will automatically switch between dense and sparse connect based on
    the network size:
    - For small networks (nodes <= degree + 1), use dense connect
    - For larger networks, use sparse connect with the specified degree

    Args:
        hosts: Sequence of hosts to connect
        degree: Number of connections each node should maintain (default: 3)

    """
    if len(hosts) <= degree + 1:
        # For small networks, use dense connect
        await dense_connect(hosts)
        return

    # For larger networks, use sparse connect
    # For each host, connect to 'degree' number of other hosts
    for i, host in enumerate(hosts):
        # Calculate which hosts to connect to
        # We'll connect to hosts that are 'degree' positions away in the sequence
        # This creates a more distributed topology
        for j in range(1, degree + 1):
            target_idx = (i + j) % len(hosts)
            # Create bidirectional connection
            await connect(host, hosts[target_idx])
            await connect(hosts[target_idx], host)

    # Ensure network connectivity by connecting each node to its immediate neighbors
    for i in range(len(hosts)):
        next_idx = (i + 1) % len(hosts)
        await connect(hosts[i], hosts[next_idx])
        await connect(hosts[next_idx], hosts[i])
