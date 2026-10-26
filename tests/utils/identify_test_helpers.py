"""Helpers for identify integration tests under parallel pytest-xdist load."""

from collections.abc import Sequence

from multiaddr import Multiaddr
import trio

from libp2p.abc import IHost
from libp2p.identity.identify.pb.identify_pb2 import Identify
from libp2p.peer.id import ID
from libp2p.utils.varint import read_length_prefixed_protobuf


async def wait_for_host_addrs(
    host: IHost,
    *,
    min_count: int = 1,
    timeout: float = 10.0,
) -> None:
    """Wait until the host advertises at least ``min_count`` listen addresses."""
    deadline = trio.current_time() + timeout
    while trio.current_time() < deadline:
        if len(host.get_addrs()) >= min_count:
            return
        await trio.sleep(0.01)
    raise TimeoutError(
        f"Host {host.get_id()} did not advertise {min_count} address(es) "
        f"within {timeout}s"
    )


async def wait_for_peerstore_addrs(
    host: IHost,
    peer_id: ID,
    *,
    expected_addrs: Sequence[Multiaddr] | None = None,
    timeout: float = 10.0,
) -> None:
    """Wait until peerstore lists addresses for ``peer_id``."""
    deadline = trio.current_time() + timeout
    while trio.current_time() < deadline:
        try:
            known = host.get_peerstore().addrs(peer_id)
        except Exception:
            known = []
        if expected_addrs is not None:
            if known and all(addr in known for addr in expected_addrs):
                return
        elif known:
            return
        await trio.sleep(0.01)
    if expected_addrs is not None:
        raise TimeoutError(
            f"Peerstore for {peer_id} missing expected addrs within {timeout}s"
        )
    raise TimeoutError(f"Peerstore for {peer_id} has no addrs within {timeout}s")


async def read_and_parse_identify(
    stream,
    *,
    use_varint_format: bool = True,
) -> Identify:
    """Read a length-prefixed or raw identify protobuf from a stream."""
    data = await read_length_prefixed_protobuf(
        stream, use_varint_format=use_varint_format
    )
    identify_msg = Identify()
    identify_msg.ParseFromString(data)
    return identify_msg
