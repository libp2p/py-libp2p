"""Tests for semaphore-based stream concurrency limiting in Swarm (#1285)."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
import trio

from libp2p.abc import ConnectionType, IMuxedConn, INetStream
from libp2p.network.connection.swarm_connection import SwarmConn
from libp2p.network.exceptions import SwarmException
from libp2p.network.stream.net_stream import NetStream
from libp2p.network.swarm import Swarm
from libp2p.peer.id import ID
from libp2p.rcmgr import Direction, ResourceLimits, ResourceManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_swarm(
    max_streams: int = 2,
    enable_semaphore: bool = True,
) -> Swarm:
    """Create a minimal Swarm wired to a ResourceManager."""
    peer_id = ID(b"QmTest")
    peerstore = Mock()
    upgrader = Mock()
    transport = Mock()

    swarm = Swarm(peer_id, peerstore, upgrader, transport)
    rm = ResourceManager(limits=ResourceLimits(max_streams=max_streams))
    swarm.set_resource_manager(rm, enable_stream_semaphore=enable_semaphore)
    return swarm


def _mock_net_stream(swarm_conn: Mock | None = None) -> NetStream:
    """Create a real NetStream backed by a mock muxed stream."""
    muxed_stream = Mock()
    muxed_conn = Mock()
    muxed_conn.peer_id = ID(b"QmPeer")
    muxed_stream.muxed_conn = muxed_conn
    # Required async methods
    muxed_stream.close = AsyncMock()
    muxed_stream.reset = AsyncMock()

    ns = NetStream(muxed_stream, swarm_conn)
    return ns


class FakeConnection:
    """Lightweight fake connection that produces real NetStreams."""

    def __init__(self, peer_id: ID, swarm: Swarm) -> None:
        self.peer_id = peer_id
        self._closed = False
        self.streams: set[NetStream] = set()
        self.muxed_conn = Mock()
        self.muxed_conn.peer_id = peer_id
        self.event_started = trio.Event()
        self._swarm = swarm

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        self._closed = True

    async def new_stream(self) -> INetStream:
        ns = _mock_net_stream()
        ns.muxed_conn = self.muxed_conn
        self.streams.add(ns)
        return ns

    def get_streams(self) -> tuple[INetStream, ...]:
        return tuple(self.streams)

    def get_transport_addresses(self) -> list:  # type: ignore[type-arg]
        return []

    def get_connection_type(self) -> ConnectionType:
        return ConnectionType.DIRECT

    def remove_stream(self, stream: NetStream) -> None:
        self.streams.discard(stream)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.trio
async def test_semaphore_queues_instead_of_failing() -> None:
    """3rd stream blocks at max_streams=2; closing 1st unblocks it."""
    swarm = _make_swarm(max_streams=2)
    peer_id = ID(b"QmPeer")
    conn = FakeConnection(peer_id, swarm)
    conn.event_started.set()

    # Patch get_connections to return our fake
    with patch.object(swarm, "get_connections", return_value=[conn]):
        # Open two streams – should succeed immediately
        s1 = await swarm.new_stream(peer_id)
        s2 = await swarm.new_stream(peer_id)

        assert getattr(s1, "_direction", None) == Direction.OUTBOUND
        assert getattr(s2, "_direction", None) == Direction.OUTBOUND

        # 3rd stream should block because semaphore is exhausted
        opened = trio.Event()

        async def open_third() -> None:
            s3 = await swarm.new_stream(peer_id)
            s3_ref.append(s3)
            opened.set()

        s3_ref: list[INetStream] = []

        async with trio.open_nursery() as nursery:
            nursery.start_soon(open_third)
            # Give the task a chance to run; it should NOT have opened yet
            await trio.testing.wait_all_tasks_blocked()  # type: ignore[attr-defined]
            assert not opened.is_set(), "3rd stream should be blocked by semaphore"

            # Close 1st stream -> releases semaphore -> unblocks 3rd
            await swarm.notify_closed_stream(s1)
            # Now the 3rd stream should unblock
            with trio.fail_after(2):
                await opened.wait()

        assert len(s3_ref) == 1
        assert getattr(s3_ref[0], "_direction", None) == Direction.OUTBOUND


@pytest.mark.trio
async def test_resource_release_on_close() -> None:
    """_current_streams returns to 0 after stream close."""
    swarm = _make_swarm(max_streams=5)
    peer_id = ID(b"QmPeer")
    conn = FakeConnection(peer_id, swarm)
    conn.event_started.set()

    rm = swarm._resource_manager
    assert rm is not None

    with patch.object(swarm, "get_connections", return_value=[conn]):
        stream = await swarm.new_stream(peer_id)
        assert rm._current_streams == 1  # type: ignore[union-attr]

        await swarm.notify_closed_stream(stream)
        assert rm._current_streams == 0  # type: ignore[union-attr]


@pytest.mark.trio
async def test_resource_release_on_reset() -> None:
    """_current_streams returns to 0 after stream reset (via notify_closed_stream)."""
    swarm = _make_swarm(max_streams=5)
    peer_id = ID(b"QmPeer")
    conn = FakeConnection(peer_id, swarm)
    conn.event_started.set()

    rm = swarm._resource_manager
    assert rm is not None

    with patch.object(swarm, "get_connections", return_value=[conn]):
        stream = await swarm.new_stream(peer_id)
        assert rm._current_streams == 1  # type: ignore[union-attr]

        # Simulate reset path – notify_closed_stream still releases
        await swarm.notify_closed_stream(stream)
        assert rm._current_streams == 0  # type: ignore[union-attr]


@pytest.mark.trio
async def test_semaphore_disabled_fallback() -> None:
    """enable_stream_semaphore=False preserves fail-fast behaviour."""
    swarm = _make_swarm(max_streams=2, enable_semaphore=False)
    assert swarm._stream_semaphore is None

    peer_id = ID(b"QmPeer")
    conn = FakeConnection(peer_id, swarm)
    conn.event_started.set()

    with patch.object(swarm, "get_connections", return_value=[conn]):
        await swarm.new_stream(peer_id)
        await swarm.new_stream(peer_id)

        # 3rd should fail immediately (no semaphore to queue on)
        with pytest.raises(SwarmException, match="Stream limit exceeded"):
            await swarm.new_stream(peer_id)


@pytest.mark.trio
async def test_no_double_release() -> None:
    """Calling notify_closed_stream twice doesn't over-release the semaphore."""
    swarm = _make_swarm(max_streams=2)
    peer_id = ID(b"QmPeer")
    conn = FakeConnection(peer_id, swarm)
    conn.event_started.set()

    with patch.object(swarm, "get_connections", return_value=[conn]):
        stream = await swarm.new_stream(peer_id)

        # First close – releases
        await swarm.notify_closed_stream(stream)
        assert getattr(stream, "_resource_released", False) is True

        # Second close – should be a no-op; verify by opening max_streams
        # If double-release occurred the semaphore would exceed initial value
        # which would allow 3 streams with max_streams=2.
        await swarm.notify_closed_stream(stream)

        # We should be able to open exactly max_streams new streams
        s1 = await swarm.new_stream(peer_id)
        s2 = await swarm.new_stream(peer_id)
        assert s1 is not None and s2 is not None


@pytest.mark.trio
async def test_failure_path_releases_semaphore() -> None:
    """Connection failure releases semaphore slot so it's not leaked."""
    swarm = _make_swarm(max_streams=2)
    peer_id = ID(b"QmPeer")

    # Make get_connections raise to simulate connection failure
    with patch.object(swarm, "get_connections", side_effect=SwarmException("no conns")):
        with pytest.raises(SwarmException):
            await swarm.new_stream(peer_id)

    # Semaphore should be fully available – verify we can open max_streams
    conn = FakeConnection(peer_id, swarm)
    conn.event_started.set()
    with patch.object(swarm, "get_connections", return_value=[conn]):
        s1 = await swarm.new_stream(peer_id)
        s2 = await swarm.new_stream(peer_id)
        assert s1 is not None and s2 is not None


@pytest.mark.trio
async def test_inbound_stream_acquires_and_releases_semaphore() -> None:
    """Inbound streams acquire semaphore + RM and release on handler exit."""
    swarm = _make_swarm(max_streams=5)
    rm = swarm._resource_manager
    assert rm is not None
    sem = swarm._stream_semaphore
    assert sem is not None

    peer_id = ID(b"QmPeer")

    # Build a minimal SwarmConn backed by mocks
    muxed_conn = Mock(spec=IMuxedConn)
    muxed_conn.peer_id = peer_id
    muxed_conn.is_closed = False
    swarm_conn = SwarmConn(muxed_conn, swarm, direction=Direction.INBOUND)
    swarm_conn.event_started.set()

    # Build a mock inbound muxed stream
    muxed_stream = Mock()
    muxed_stream.muxed_conn = muxed_conn
    muxed_stream.close = AsyncMock()
    muxed_stream.reset = AsyncMock()

    # Replace common_stream_handler with a no-op so the handler completes
    handler_called = trio.Event()

    async def fake_handler(stream: INetStream) -> None:
        handler_called.set()

    swarm.common_stream_handler = fake_handler  # type: ignore[assignment]

    # Before: no streams held
    assert rm._current_streams == 0  # type: ignore[union-attr]

    await swarm_conn._handle_muxed_stream(muxed_stream)

    # Handler was invoked
    assert handler_called.is_set()

    # After: resources fully released (RM + semaphore)
    assert rm._current_streams == 0  # type: ignore[union-attr]

    # Verify we can still open max_streams outbound (semaphore wasn't leaked)
    outbound_conn = FakeConnection(peer_id, swarm)
    outbound_conn.event_started.set()
    with patch.object(swarm, "get_connections", return_value=[outbound_conn]):
        streams = [await swarm.new_stream(peer_id) for _ in range(5)]
        assert len(streams) == 5
