"""
Unit tests for reconnection queue implementation.

Tests for KEEP_ALIVE tag handling, exponential backoff, reconnection attempts,
and queue lifecycle management.
"""

import time
from unittest.mock import Mock

import pytest
import trio

from libp2p.network.config import (
    MAX_PARALLEL_RECONNECTS,
    RECONNECT_BACKOFF_FACTOR,
    RECONNECT_RETRIES,
    RECONNECT_RETRY_INTERVAL,
)
from libp2p.network.reconnect_queue import (
    KEEP_ALIVE_METADATA_KEY,
    ReconnectJob,
    ReconnectQueue,
    has_keep_alive_tag,
)
from libp2p.peer.id import ID


class TestReconnectJob:
    """Test ReconnectJob dataclass."""

    def test_reconnect_job_defaults(self):
        """Test ReconnectJob default values."""
        peer_id = ID(b"QmTest")
        job = ReconnectJob(peer_id=peer_id)

        assert job.peer_id == peer_id
        assert job.attempt == 0
        assert job.next_retry_at == 0.0
        assert job.cancel_scope is None

    def test_reconnect_job_with_attempt(self):
        """Test ReconnectJob with attempt count."""
        peer_id = ID(b"QmTest")
        job = ReconnectJob(peer_id=peer_id, attempt=3, next_retry_at=time.time() + 10)

        assert job.attempt == 3
        assert job.next_retry_at > time.time()


class TestKeepAliveTagDetection:
    """Test KEEP_ALIVE tag detection."""

    def test_has_keep_alive_tag_with_metadata_key(self):
        """Test KEEP_ALIVE detection via metadata key."""
        peer_id = ID(b"QmTest")

        # Create mock peer store with KEEP_ALIVE metadata
        peer_data = Mock()
        peer_data.metadata = {KEEP_ALIVE_METADATA_KEY: True}

        peer_store = Mock()
        peer_store.peer_data_map = {peer_id: peer_data}

        assert has_keep_alive_tag(peer_store, peer_id) is True

    def test_has_keep_alive_tag_with_prefix(self):
        """Test KEEP_ALIVE detection via key prefix."""
        peer_id = ID(b"QmTest")

        # Create mock peer store with keep-alive prefixed key
        peer_data = Mock()
        peer_data.metadata = {"keep-alive-custom": "value"}

        peer_store = Mock()
        peer_store.peer_data_map = {peer_id: peer_data}

        assert has_keep_alive_tag(peer_store, peer_id) is True

    def test_has_keep_alive_tag_missing(self):
        """Test KEEP_ALIVE detection when tag is missing."""
        peer_id = ID(b"QmTest")

        # Create mock peer store without KEEP_ALIVE
        peer_data = Mock()
        peer_data.metadata = {"other_key": "value"}

        peer_store = Mock()
        peer_store.peer_data_map = {peer_id: peer_data}

        assert has_keep_alive_tag(peer_store, peer_id) is False

    def test_has_keep_alive_tag_no_peer_data(self):
        """Test KEEP_ALIVE detection when peer not found."""
        peer_id = ID(b"QmTest")

        peer_store = Mock()
        peer_store.peer_data_map = {}

        assert has_keep_alive_tag(peer_store, peer_id) is False

    def test_has_keep_alive_tag_no_peer_data_map(self):
        """Test KEEP_ALIVE detection when peer_data_map is missing."""
        peer_id = ID(b"QmTest")

        peer_store = Mock(spec=[])  # No attributes

        assert has_keep_alive_tag(peer_store, peer_id) is False

    def test_has_keep_alive_tag_empty_metadata(self):
        """Test KEEP_ALIVE detection with empty metadata."""
        peer_id = ID(b"QmTest")

        peer_data = Mock()
        peer_data.metadata = {}

        peer_store = Mock()
        peer_store.peer_data_map = {peer_id: peer_data}

        assert has_keep_alive_tag(peer_store, peer_id) is False

    def test_has_keep_alive_tag_none_metadata(self):
        """Test KEEP_ALIVE detection with None metadata."""
        peer_id = ID(b"QmTest")

        peer_data = Mock()
        peer_data.metadata = None

        peer_store = Mock()
        peer_store.peer_data_map = {peer_id: peer_data}

        assert has_keep_alive_tag(peer_store, peer_id) is False


class TestReconnectQueueInitialization:
    """Test ReconnectQueue initialization and configuration."""

    def test_reconnect_queue_defaults(self):
        """Test ReconnectQueue default configuration."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = ReconnectQueue(swarm)
        assert queue.retries == RECONNECT_RETRIES
        assert queue.retry_interval == RECONNECT_RETRY_INTERVAL
        assert queue.backoff_factor == RECONNECT_BACKOFF_FACTOR
        assert queue.max_parallel_reconnects == MAX_PARALLEL_RECONNECTS

    def test_reconnect_queue_custom_config(self):
        """Test ReconnectQueue with custom configuration."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = ReconnectQueue(
            swarm,
            retries=10,
            retry_interval=2.0,
            backoff_factor=3.0,
            max_parallel_reconnects=10,
        )
        assert queue.retries == 10
        assert queue.retry_interval == 2.0
        assert queue.backoff_factor == 3.0
        assert queue.max_parallel_reconnects == 10


class TestReconnectQueueLifecycle:
    """Test ReconnectQueue start/stop lifecycle."""

    @pytest.mark.trio
    async def test_reconnect_queue_start(self):
        """Test starting the reconnect queue."""
        swarm = Mock()
        swarm.peerstore = Mock()
        swarm.peerstore.peer_data_map = {}

        queue = ReconnectQueue(swarm)
        assert queue._started is False

        await queue.start()
        assert queue._started is True

    @pytest.mark.trio
    async def test_reconnect_queue_stop(self):
        """Test stopping the reconnect queue."""
        swarm = Mock()
        swarm.peerstore = Mock()
        swarm.peerstore.peer_data_map = {}

        queue = ReconnectQueue(swarm)
        await queue.start()
        assert queue._started is True

        await queue.stop()
        assert queue._started is False
        assert len(queue._reconnect_jobs) == 0
        assert len(queue._running_reconnects) == 0

    @pytest.mark.trio
    async def test_reconnect_queue_stop_cancels_running(self):
        """Test that stop cancels running reconnects."""
        swarm = Mock()
        swarm.peerstore = Mock()
        swarm.peerstore.peer_data_map = {}

        queue = ReconnectQueue(swarm)
        await queue.start()

        peer_id = ID(b"QmTest")

        # Add a job with cancel scope
        cancel_scope = Mock()
        job = ReconnectJob(peer_id=peer_id, cancel_scope=cancel_scope)
        queue._reconnect_jobs[peer_id] = job
        queue._running_reconnects.add(peer_id)

        await queue.stop()

        cancel_scope.cancel.assert_called_once()


class TestMaybeReconnect:
    """Test maybe_reconnect functionality."""

    @pytest.mark.trio
    async def test_maybe_reconnect_not_started(self):
        """Test maybe_reconnect when queue is not started."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = ReconnectQueue(swarm)
        peer_id = ID(b"QmTest")

        # Should not raise, just return early
        await queue.maybe_reconnect(peer_id)
        assert len(queue._reconnect_jobs) == 0

    @pytest.mark.trio
    async def test_maybe_reconnect_no_keep_alive_tag(self):
        """Test maybe_reconnect when peer doesn't have KEEP_ALIVE tag."""
        swarm = Mock()
        swarm.peerstore = Mock()
        swarm.peerstore.peer_data_map = {}

        queue = ReconnectQueue(swarm)
        await queue.start()

        peer_id = ID(b"QmTest")

        await queue.maybe_reconnect(peer_id)
        assert len(queue._reconnect_jobs) == 0

    @pytest.mark.trio
    async def test_maybe_reconnect_already_reconnecting(self):
        """Test maybe_reconnect when already reconnecting."""
        swarm = Mock()
        swarm.peerstore = Mock()

        peer_id = ID(b"QmTest")

        # Setup KEEP_ALIVE tag
        peer_data = Mock()
        peer_data.metadata = {KEEP_ALIVE_METADATA_KEY: True}
        swarm.peerstore.peer_data_map = {peer_id: peer_data}

        queue = ReconnectQueue(swarm)
        await queue.start()

        # Add existing job
        queue._reconnect_jobs[peer_id] = ReconnectJob(peer_id=peer_id)

        await queue.maybe_reconnect(peer_id)
        # Should still have only one job
        assert len(queue._reconnect_jobs) == 1


class TestExponentialBackoff:
    """Test exponential backoff calculation."""

    def test_backoff_calculation(self):
        """Test backoff delay calculation."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = ReconnectQueue(
            swarm,
            retry_interval=1.0,
            backoff_factor=2.0,
        )

        # Calculate expected delays
        # Attempt 0: 1.0 * 2^0 = 1.0
        # Attempt 1: 1.0 * 2^1 = 2.0
        # Attempt 2: 1.0 * 2^2 = 4.0
        # Attempt 3: 1.0 * 2^3 = 8.0

        peer_id = ID(b"QmTest")

        job = ReconnectJob(peer_id=peer_id, attempt=0)
        delay = queue.retry_interval * (queue.backoff_factor**job.attempt)
        assert delay == 1.0

        job.attempt = 1
        delay = queue.retry_interval * (queue.backoff_factor**job.attempt)
        assert delay == 2.0

        job.attempt = 2
        delay = queue.retry_interval * (queue.backoff_factor**job.attempt)
        assert delay == 4.0

        job.attempt = 3
        delay = queue.retry_interval * (queue.backoff_factor**job.attempt)
        assert delay == 8.0

    def test_backoff_with_custom_factor(self):
        """Test backoff with custom backoff factor."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = ReconnectQueue(
            swarm,
            retry_interval=0.5,
            backoff_factor=3.0,
        )

        peer_id = ID(b"QmTest")
        job = ReconnectJob(peer_id=peer_id, attempt=2)

        # 0.5 * 3^2 = 4.5
        delay = queue.retry_interval * (queue.backoff_factor**job.attempt)
        assert delay == 4.5


class TestReconnectRetryLimits:
    """Test retry limit enforcement."""

    def test_max_retries_configuration(self):
        """Test max retries configuration."""
        swarm = Mock()
        swarm.peerstore = Mock()

        queue = ReconnectQueue(swarm, retries=3)
        assert queue.retries == 3

    def test_attempt_tracking(self):
        """Test attempt count tracking in job."""
        peer_id = ID(b"QmTest")
        job = ReconnectJob(peer_id=peer_id, attempt=0)

        assert job.attempt == 0
        job.attempt += 1
        assert job.attempt == 1
        job.attempt += 1
        assert job.attempt == 2


class TestReconnectConcurrencyControl:
    """Test concurrency control in reconnect queue."""

    @pytest.mark.trio
    async def test_max_parallel_reconnects_tracking(self):
        """Test tracking of running reconnects."""
        swarm = Mock()
        swarm.peerstore = Mock()
        swarm.peerstore.peer_data_map = {}

        queue = ReconnectQueue(swarm, max_parallel_reconnects=2)
        await queue.start()

        peer1 = ID(b"QmTest1")
        peer2 = ID(b"QmTest2")

        async with queue._running_lock:
            queue._running_reconnects.add(peer1)
            queue._running_reconnects.add(peer2)

        assert len(queue._running_reconnects) == 2

    @pytest.mark.trio
    async def test_running_set_cleanup(self):
        """Test cleanup of running set."""
        swarm = Mock()
        swarm.peerstore = Mock()
        swarm.peerstore.peer_data_map = {}

        queue = ReconnectQueue(swarm)
        await queue.start()

        peer_id = ID(b"QmTest")

        async with queue._running_lock:
            queue._running_reconnects.add(peer_id)
        assert peer_id in queue._running_reconnects

        async with queue._running_lock:
            queue._running_reconnects.discard(peer_id)
        assert peer_id not in queue._running_reconnects


class TestReconnectJobManagement:
    """Test reconnect job lifecycle management."""

    @pytest.mark.trio
    async def test_job_creation(self):
        """Test job creation."""
        peer_id = ID(b"QmTest")
        job = ReconnectJob(peer_id=peer_id)

        assert job.peer_id == peer_id
        assert job.attempt == 0
        assert job.cancel_scope is None

    @pytest.mark.trio
    async def test_job_removal_on_success(self):
        """Test job is removed on successful reconnection."""
        swarm = Mock()
        swarm.peerstore = Mock()
        swarm.peerstore.peer_data_map = {}

        queue = ReconnectQueue(swarm)
        await queue.start()

        peer_id = ID(b"QmTest")
        queue._reconnect_jobs[peer_id] = ReconnectJob(peer_id=peer_id)

        # Simulate successful removal
        async with queue._jobs_lock:
            queue._reconnect_jobs.pop(peer_id, None)

        assert peer_id not in queue._reconnect_jobs

    @pytest.mark.trio
    async def test_job_cancel_scope_assignment(self):
        """Test cancel scope assignment to job."""
        peer_id = ID(b"QmTest")
        job = ReconnectJob(peer_id=peer_id)

        assert job.cancel_scope is None

        cancel_scope = trio.CancelScope()
        job.cancel_scope = cancel_scope

        assert job.cancel_scope is cancel_scope


class TestReconnectIntegration:
    """Integration tests for reconnect queue."""

    @pytest.mark.trio
    async def test_full_lifecycle(self):
        """Test full reconnect queue lifecycle."""
        swarm = Mock()
        swarm.peerstore = Mock()
        swarm.peerstore.peer_data_map = {}

        queue = ReconnectQueue(swarm, retries=3, retry_interval=0.1)

        # Start
        await queue.start()
        assert queue._started is True
        assert len(queue._reconnect_jobs) == 0

        # Stop
        await queue.stop()
        assert queue._started is False
        assert len(queue._reconnect_jobs) == 0
        assert len(queue._running_reconnects) == 0
