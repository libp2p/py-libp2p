"""Regression tests for bounded Bitswap state and unreachable providers."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import trio

from libp2p.bitswap.cid import compute_cid_v1
from libp2p.bitswap.client import BitswapClient
from libp2p.bitswap.message_queue import BitswapMessageQueue
from libp2p.bitswap.messages import create_message, create_wantlist_entry
from libp2p.bitswap.session import BitswapSession
from libp2p.peer.id import ID


class _UnreachableHost:
    """Host whose peerstore has no addresses and whose dials always fail."""

    def __init__(self) -> None:
        self.dials = 0
        self.network = SimpleNamespace(
            connections={},
            register_notifee=lambda notifee: None,
            remove_notifee=lambda notifee: None,
        )
        self.peerstore = SimpleNamespace(addrs=lambda peer_id: [])

    def set_stream_handler(self, *args) -> None:
        pass

    def remove_stream_handler(self, *args) -> None:
        pass

    def get_network(self):
        return self.network

    def get_event_bus(self):
        return SimpleNamespace(emit=lambda event: None)

    async def new_stream(self, *args):
        self.dials += 1
        raise OSError("controlled unreachable provider")


@pytest.mark.trio
async def test_unreachable_provider_creates_no_queue_or_wants():
    host = _UnreachableHost()
    client = BitswapClient(host)
    async with trio.open_nursery() as nursery:
        client.set_nursery(nursery)
        await client.start()

        session = BitswapSession(client, 1)
        cid = compute_cid_v1(b"unreachable")
        with pytest.raises(Exception, match="Timeout"):
            await session.get_block(cid, peer_id=ID(b"peer"), timeout=0.01)

        assert client._message_queues == {}
        assert client._wants_sent_to_peer == {}
        assert not any(queue._started for queue in client._message_queues.values())
        nursery.cancel_scope.cancel()


@pytest.mark.trio
async def test_duplicate_batch_cids_leave_no_pending_events():
    client = BitswapClient(_UnreachableHost())
    session = BitswapSession(client, 1)
    cid = compute_cid_v1(b"duplicate")

    await session.get_blocks_batch([cid, cid], timeout=0.001)

    assert session._pending_requests == {}


def test_message_queue_bounds_wants_and_blocks():
    host = _UnreachableHost()
    queue = BitswapMessageQueue(host, ID(b"peer"), ["/ipfs/bitswap/1.0.0"])

    with (
        patch("libp2p.bitswap.message_queue.MAX_PENDING_WANTS_PER_PEER", 5),
        patch("libp2p.bitswap.message_queue.MAX_PENDING_BLOCKS_PER_PEER", 4),
        patch("libp2p.bitswap.message_queue.MAX_PENDING_BLOCK_BYTES_PER_PEER", 8),
    ):
        for i in range(20):
            queue.add_wants([compute_cid_v1(str(i).encode())])
        for i in range(20):
            queue.add_blocks_v100([bytes([i])])

        assert len(queue._pending_wants) == 5
        assert len(queue._pending_blocks_v100) <= 4
        assert sum(map(len, queue._pending_blocks_v100)) <= 8


@pytest.mark.trio
async def test_inbound_wantlist_is_capped():
    client = BitswapClient(_UnreachableHost())
    peer = ID(b"peer")

    with patch("libp2p.bitswap.client.MAX_PEER_WANTLIST_ENTRIES", 5):
        for i in range(20):
            cid = compute_cid_v1(str(i).encode())
            msg = create_message(
                wantlist_entries=[
                    create_wantlist_entry(cid, want_type=0, send_dont_have=False)
                ]
            )
            await client._process_wantlist(msg.wantlist, peer, None)

        assert len(client._peer_wantlists[peer]) == 5

        full = create_message(full_wantlist=True)
        full.wantlist.full = True
        await client._process_wantlist(full.wantlist, peer, None)
        assert client._peer_wantlists[peer] == {}
