"""
Method-level tests for KadDHT sliding-window scheduling and quorum early-stop.

These tests instantiate real KadDHT objects and mock the underlying
_get_from_peer / _store_at_peer calls to verify that the semaphore-based
concurrency works end-to-end through the actual put_value / get_value paths.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
from libp2p.kad_dht.pb.kademlia_pb2 import Record
from libp2p.peer.id import ID
from libp2p.records.validator import Validator


def _make_peer_id(name: str) -> ID:
    key_pair = create_new_key_pair()
    return ID.from_pubkey(key_pair.public_key)


class SimpleValidator(Validator):
    """Accepts all byte values, selects the first."""

    def validate(self, key: str, value: bytes) -> None:
        if not isinstance(value, bytes):
            raise TypeError("Value must be bytes")

    def select(self, key: str, values: list[bytes]) -> int:
        return 0


def _make_dht() -> KadDHT:
    """Build a KadDHT with a mock host and simple validator."""
    host = MagicMock()
    key_pair = create_new_key_pair()
    host.get_id.return_value = ID.from_pubkey(key_pair.public_key)
    host.get_addrs.return_value = [Multiaddr("/ip4/127.0.0.1/tcp/8000")]
    host.get_peerstore.return_value = MagicMock()
    host.new_stream = AsyncMock()

    from libp2p.records.validator import NamespacedValidator

    validator = NamespacedValidator(
        {"test": SimpleValidator()}, strict_validation=False
    )
    dht = KadDHT(host, DHTMode.SERVER, validator=validator)
    return dht


# ---------------------------------------------------------------------------
# get_value: quorum early-stop through real method
# ---------------------------------------------------------------------------


class TestGetValueQuorumEarlyStop:
    """Call KadDHT.get_value() with mocked peers."""

    @pytest.mark.trio
    async def test_get_value_stops_after_quorum(self):
        """
        With 8 closest peers and quorum=2, get_value should not
        query all 8.
        """
        dht = _make_dht()
        peers = [_make_peer_id(f"peer{i}") for i in range(8)]
        query_count: list[int] = [0]

        async def mock_get(peer, key_bytes, return_record=False):
            query_count[0] += 1
            idx = peers.index(peer)
            if idx < 3:
                await trio.sleep(0.01)
                rec = Record()
                rec.key = key_bytes
                rec.value = b"test-value"
                rec.timeReceived = str(int(time.time()))
                return rec
            else:
                await trio.sleep(1.0)
                return None

        with (
            patch.object(
                dht.routing_table,
                "find_local_closest_peers",
                return_value=peers,
            ),
            patch.object(dht.value_store, "get", return_value=None),
            patch.object(dht.value_store, "_get_from_peer", side_effect=mock_get),
            patch.object(dht, "validator", SimpleValidator()),
        ):
            result = await dht.get_value("test-key", quorum=2)

        assert result == b"test-value"
        assert query_count[0] <= 5, (
            f"Expected at most ~4-5 queries with quorum=2, ALPHA=3, "
            f"but got {query_count[0]}."
        )

    @pytest.mark.trio
    async def test_get_value_no_quorum_queries_all(self):
        """With quorum=0, get_value should query all peers."""
        dht = _make_dht()
        peers = [_make_peer_id(f"peer{i}") for i in range(5)]
        query_count: list[int] = [0]

        async def mock_get(peer, key_bytes, return_record=False):
            query_count[0] += 1
            await trio.sleep(0.01)
            rec = Record()
            rec.key = key_bytes
            rec.value = b"val"
            rec.timeReceived = str(int(time.time()))
            return rec

        with (
            patch.object(
                dht.routing_table,
                "find_local_closest_peers",
                return_value=peers,
            ),
            patch.object(dht.value_store, "get", return_value=None),
            patch.object(dht.value_store, "_get_from_peer", side_effect=mock_get),
            patch.object(dht, "validator", SimpleValidator()),
        ):
            result = await dht.get_value("test-key", quorum=0)

        assert result == b"val"
        assert query_count[0] == 5, (
            f"All 5 peers should be queried, got {query_count[0]}"
        )


# ---------------------------------------------------------------------------
# put_value: sliding-window scheduling through real method
# ---------------------------------------------------------------------------


class TestPutValueSlidingWindow:
    """Call KadDHT.put_value() with mocked peers."""

    @pytest.mark.trio
    async def test_put_value_sliding_window_no_idle(self):
        """
        With 5 peers and one slow peer, verify peer 3 starts before
        slow peer 2 finishes.
        """
        dht = _make_dht()
        peers = [_make_peer_id(f"peer{i}") for i in range(5)]
        started_at: dict[int, float] = {}

        async def mock_store(peer, key_bytes, value):
            idx = peers.index(peer)
            started_at[idx] = trio.current_time()
            if idx == 2:
                await trio.sleep(0.5)
            else:
                await trio.sleep(0.01)
            return True

        with (
            patch.object(
                dht.routing_table,
                "find_local_closest_peers",
                return_value=peers,
            ),
            patch.object(
                dht.value_store,
                "_store_at_peer",
                side_effect=mock_store,
            ),
            patch.object(dht, "validator", SimpleValidator()),
        ):
            await dht.put_value("test-key", b"test-value")

        assert len(started_at) == 5, (
            f"All 5 peers should be stored to, got {len(started_at)}"
        )
        assert started_at[3] < started_at[2] + 0.3, (
            f"Peer 3 started at {started_at[3]:.3f}, "
            f"peer 2 at {started_at[2]:.3f}. "
            "Sliding window not working."
        )

    @pytest.mark.trio
    async def test_put_value_counts_successes(self):
        """Verify put_value attempts all peers."""
        dht = _make_dht()
        peers = [_make_peer_id(f"peer{i}") for i in range(4)]
        call_count: list[int] = [0]

        async def mock_store(peer, key_bytes, value):
            call_count[0] += 1
            idx = peers.index(peer)
            await trio.sleep(0.01)
            return idx in (0, 2)

        with (
            patch.object(
                dht.routing_table,
                "find_local_closest_peers",
                return_value=peers,
            ),
            patch.object(
                dht.value_store,
                "_store_at_peer",
                side_effect=mock_store,
            ),
            patch.object(dht, "validator", SimpleValidator()),
        ):
            await dht.put_value("test-key", b"test-value")

        assert call_count[0] == 4, (
            f"All 4 peers should be attempted, got {call_count[0]}"
        )


# ---------------------------------------------------------------------------
# get_value: sliding-window scheduling through real method
# ---------------------------------------------------------------------------


class TestGetValueSlidingWindow:
    """Call KadDHT.get_value() with mixed-latency mocked peers."""

    @pytest.mark.trio
    async def test_get_value_sliding_window_no_idle(self):
        """
        With 5 peers and one slow peer, peer 3 should start before
        slow peer 2 finishes.
        """
        dht = _make_dht()
        peers = [_make_peer_id(f"peer{i}") for i in range(5)]
        started_at: dict[int, float] = {}

        async def mock_get(peer, key_bytes, return_record=False):
            idx = peers.index(peer)
            started_at[idx] = trio.current_time()
            if idx == 2:
                await trio.sleep(0.5)
            else:
                await trio.sleep(0.01)
            rec = Record()
            rec.key = key_bytes
            rec.value = b"val"
            rec.timeReceived = str(int(time.time()))
            return rec

        with (
            patch.object(
                dht.routing_table,
                "find_local_closest_peers",
                return_value=peers,
            ),
            patch.object(dht.value_store, "get", return_value=None),
            patch.object(dht.value_store, "_get_from_peer", side_effect=mock_get),
            patch.object(dht, "validator", SimpleValidator()),
        ):
            result = await dht.get_value("test-key", quorum=0)

        assert result == b"val"
        assert len(started_at) == 5
        assert started_at[3] < started_at[2] + 0.3, (
            f"Peer 3 started at {started_at[3]:.3f}, "
            f"peer 2 at {started_at[2]:.3f}. "
            "Sliding window not working in get_value."
        )
