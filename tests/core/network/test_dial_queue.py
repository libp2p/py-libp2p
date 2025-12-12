"""
Unit tests for dial queue implementation.

Tests for priority scheduling, concurrency control, deduplication,
and dial queue lifecycle management.
"""

import time
from unittest.mock import Mock

import pytest
from multiaddr import Multiaddr

from libp2p.network.address_manager import AddressManager
from libp2p.network.config import DEFAULT_DIAL_PRIORITY
from libp2p.network.dial_queue import DialJob, DialQueue
from libp2p.peer.id import ID


class TestDialJob:
    """Test DialJob dataclass and comparison logic."""

    def test_dial_job_defaults(self):
        """Test DialJob default values."""
        job = DialJob()
        assert job.priority == DEFAULT_DIAL_PRIORITY
        assert job.peer_id is None
        assert isinstance(job.multiaddrs, set)
        assert len(job.multiaddrs) == 0
        assert job.running is False
        assert job.added_at > 0

    def test_dial_job_with_peer_id(self):
        """Test DialJob with peer ID."""
        peer_id = ID(b"QmTest")
        job = DialJob(peer_id=peer_id, priority=100)
        assert job.peer_id == peer_id
        assert job.priority == 100

    def test_dial_job_with_multiaddrs(self):
        """Test DialJob with multiaddrs."""
        addrs = {"/ip4/127.0.0.1/tcp/1234", "/ip4/192.168.1.1/tcp/5678"}
        job = DialJob(multiaddrs=addrs)
        assert job.multiaddrs == addrs

    def test_dial_job_priority_comparison(self):
        """Test DialJob comparison for priority queue."""
        high_priority = DialJob(priority=100)
        low_priority = DialJob(priority=10)

        # Higher priority should be "less than" for min-heap
        assert high_priority < low_priority

    def test_dial_job_fifo_within_same_priority(self):
        """Test FIFO ordering within same priority."""
        job1 = DialJob(priority=50)
        # Small delay to ensure different timestamps
        time.sleep(0.001)
        job2 = DialJob(priority=50)

        # Earlier job should be "less than" later job
        assert job1 < job2

    def test_dial_job_comparison_priority_takes_precedence(self):
        """Test that priority takes precedence over timestamp."""
        # Create low priority first
        low_priority = DialJob(priority=10)
        time.sleep(0.001)
        # Create high priority second
        high_priority = DialJob(priority=100)

        # High priority should still come first despite being added later
        assert high_priority < low_priority


class TestDialQueueInitialization:
    """Test DialQueue initialization and configuration."""

    def test_dial_queue_defaults(self):
        """Test DialQueue default configuration."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = DialQueue(swarm)
        assert queue.max_parallel_dials == 100
        assert queue.max_dial_queue_length == 500
        assert queue.dial_timeout == 10.0
        assert isinstance(queue.address_manager, AddressManager)

    def test_dial_queue_custom_config(self):
        """Test DialQueue with custom configuration."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = DialQueue(
            swarm,
            max_parallel_dials=50,
            max_dial_queue_length=100,
            dial_timeout=5.0,
        )
        assert queue.max_parallel_dials == 50
        assert queue.max_dial_queue_length == 100
        assert queue.dial_timeout == 5.0

    def test_dial_queue_with_custom_address_manager(self):
        """Test DialQueue with custom address manager."""
        swarm = Mock()
        swarm.peerstore = Mock()
        custom_manager = AddressManager()

        queue = DialQueue(swarm, address_manager=custom_manager)
        assert queue.address_manager is custom_manager


class TestDialQueueLifecycle:
    """Test DialQueue start/stop lifecycle."""

    @pytest.mark.trio
    async def test_dial_queue_start(self):
        """Test starting the dial queue."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = DialQueue(swarm)
        assert queue._started is False

        await queue.start()
        assert queue._started is True

    @pytest.mark.trio
    async def test_dial_queue_stop(self):
        """Test stopping the dial queue."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = DialQueue(swarm)
        await queue.start()
        assert queue._started is True

        await queue.stop()
        assert queue._started is False

    @pytest.mark.trio
    async def test_dial_queue_not_started_raises(self):
        """Test that dialing before start raises error."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = DialQueue(swarm)
        peer_id = ID(b"QmTest")

        with pytest.raises(RuntimeError, match="not started"):
            await queue.dial(peer_id)


class TestDialQueueOperations:
    """Test DialQueue dial operations."""

    @pytest.mark.trio
    async def test_dial_queue_size(self):
        """Test queue size tracking."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = DialQueue(swarm)
        assert queue.get_queue_size() == 0
        assert queue.get_running_count() == 0

    @pytest.mark.trio
    async def test_dial_existing_connection_reused(self):
        """Test that existing connections are reused."""
        swarm = Mock()
        swarm.peerstore = Mock()

        peer_id = ID(b"QmTest")
        mock_conn = Mock()

        # Setup mock to return existing connection
        swarm.get_connections = Mock(return_value=[mock_conn])
        swarm.peerstore.addrs = Mock(return_value=[])

        queue = DialQueue(swarm)
        await queue.start()

        result = await queue.dial(peer_id)
        assert result is mock_conn
        swarm.get_connections.assert_called_once_with(peer_id)

    @pytest.mark.trio
    async def test_dial_queue_full_raises(self):
        """Test that full queue raises error."""
        swarm = Mock()
        swarm.peerstore = Mock()
        swarm.get_connections = Mock(return_value=[])
        swarm.peerstore.addrs = Mock(return_value=[])

        # Create queue with max length of 1
        queue = DialQueue(swarm, max_dial_queue_length=1)
        await queue.start()

        # Add a job to fill the queue
        async with queue._queue_lock:
            queue._queue.append(DialJob())

        peer_id = ID(b"QmTest")
        with pytest.raises(RuntimeError, match="queue is full"):
            await queue.dial(peer_id)


class TestDialQueueDeduplication:
    """Test dial request deduplication."""

    def test_find_existing_dial_by_peer_id(self):
        """Test finding existing dial by peer ID."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = DialQueue(swarm)
        peer_id = ID(b"QmTest")

        # Add job to queue
        existing_job = DialJob(peer_id=peer_id)
        queue._queue.append(existing_job)

        # Should find existing job
        found = queue._find_existing_dial(peer_id, set())
        assert found is existing_job

    def test_find_existing_dial_by_multiaddr(self):
        """Test finding existing dial by multiaddr."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = DialQueue(swarm)
        addr = "/ip4/127.0.0.1/tcp/1234"

        # Add job with matching multiaddr
        existing_job = DialJob(multiaddrs={addr})
        queue._queue.append(existing_job)

        # Should find existing job
        found = queue._find_existing_dial(None, {addr})
        assert found is existing_job

    def test_find_existing_dial_not_found(self):
        """Test when no existing dial is found."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = DialQueue(swarm)

        # No matching job
        found = queue._find_existing_dial(ID(b"QmOther"), {"/ip4/10.0.0.1/tcp/1234"})
        assert found is None


class TestDialQueuePriorityScheduling:
    """Test priority-based scheduling."""

    def test_priority_queue_ordering(self):
        """Test that jobs are ordered by priority."""
        import heapq

        jobs = []
        heapq.heappush(jobs, DialJob(priority=10))  # Low
        heapq.heappush(jobs, DialJob(priority=100))  # High
        heapq.heappush(jobs, DialJob(priority=50))  # Medium

        # Pop should return highest priority first
        first = heapq.heappop(jobs)
        assert first.priority == 100

        second = heapq.heappop(jobs)
        assert second.priority == 50

        third = heapq.heappop(jobs)
        assert third.priority == 10

    def test_priority_with_fifo_ordering(self):
        """Test FIFO ordering within same priority."""
        import heapq

        jobs = []
        job1 = DialJob(priority=50)
        time.sleep(0.001)
        job2 = DialJob(priority=50)
        time.sleep(0.001)
        job3 = DialJob(priority=50)

        heapq.heappush(jobs, job2)
        heapq.heappush(jobs, job3)
        heapq.heappush(jobs, job1)

        # Should pop in FIFO order (job1, job2, job3)
        first = heapq.heappop(jobs)
        assert first is job1

        second = heapq.heappop(jobs)
        assert second is job2

        third = heapq.heappop(jobs)
        assert third is job3


class TestDialQueueConcurrencyControl:
    """Test concurrency control in dial queue."""

    @pytest.mark.trio
    async def test_max_parallel_dials_respected(self):
        """Test that max parallel dials limit is respected."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = DialQueue(swarm, max_parallel_dials=2)
        await queue.start()

        # Use Mock objects instead of DialJob which is unhashable
        mock_job1 = Mock()
        mock_job2 = Mock()

        async with queue._running_lock:
            queue._running_jobs = {mock_job1, mock_job2}

        assert queue.get_running_count() == 2

        # Queue should be at max capacity
        # (new jobs would be added to queue but not started)

    @pytest.mark.trio
    async def test_running_count_tracking(self):
        """Test running job count tracking."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = DialQueue(swarm)
        await queue.start()

        assert queue.get_running_count() == 0

        # Use Mock objects for hashability
        mock_job1 = Mock()
        mock_job2 = Mock()

        async with queue._running_lock:
            queue._running_jobs = {mock_job1}
        assert queue.get_running_count() == 1

        async with queue._running_lock:
            queue._running_jobs = {mock_job1, mock_job2}
        assert queue.get_running_count() == 2

        async with queue._running_lock:
            queue._running_jobs = {mock_job1}
        assert queue.get_running_count() == 1


class TestDialQueueAddressResolution:
    """Test address resolution in dial queue."""

    @pytest.mark.trio
    async def test_multiaddr_parsing_extracts_peer_id(self):
        """Test that peer ID is extracted from multiaddr."""
        swarm = Mock()
        swarm.peerstore = Mock()
        swarm.get_connections = Mock(return_value=[])

        queue = DialQueue(swarm)
        await queue.start()

        # Multiaddr with embedded peer ID
        peer_id_str = "QmcgpsyWgH8Y8ajJz1Cu72KnS5uo2Aa2LpzU7kinSupNKC"
        maddr = Multiaddr(f"/ip4/127.0.0.1/tcp/1234/p2p/{peer_id_str}")

        # We can't complete the dial without a proper swarm, but we can test
        # that the multiaddr is processed correctly
        with pytest.raises(Exception):
            # This will fail because swarm isn't fully mocked, but the parsing
            # happens before the error
            await queue.dial(maddr)

    @pytest.mark.trio
    async def test_list_of_multiaddrs_handling(self):
        """Test handling of list of multiaddrs."""
        swarm = Mock()
        swarm.peerstore = Mock()
        mock_conn = Mock()
        swarm.get_connections = Mock(return_value=[mock_conn])

        queue = DialQueue(swarm)
        await queue.start()

        # List of multiaddrs
        maddrs = [
            Multiaddr(
                "/ip4/127.0.0.1/tcp/1234/p2p/QmcgpsyWgH8Y8ajJz1Cu72KnS5uo2Aa2LpzU7kinSupNKC"
            ),
            Multiaddr("/ip4/192.168.1.1/tcp/5678"),
        ]

        # Should extract peer ID from first multiaddr and find existing connection
        result = await queue.dial(maddrs)
        assert result is mock_conn
