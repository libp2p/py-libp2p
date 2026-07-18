import pytest
import trio

from libp2p.tools.timed_cache.first_seen_cache import (
    FirstSeenCache,
)
from libp2p.tools.timed_cache.last_seen_cache import (
    LastSeenCache,
)

MSG_1 = b"msg1"


@pytest.mark.trio
async def test_simple_first_seen_cache():
    """Test that FirstSeenCache correctly stores and retrieves messages."""
    cache = FirstSeenCache(ttl=2, sweep_interval=1)

    assert cache.add(MSG_1) is True  # First addition should return True
    assert cache.has(MSG_1) is True  # Should exist
    assert cache.add(MSG_1) is False  # Duplicate should return False

    await trio.sleep(2.5)  # Wait beyond TTL
    assert cache.has(MSG_1) is False  # Should be expired

    cache.stop()


@pytest.mark.trio
async def test_simple_last_seen_cache():
    """Test that LastSeenCache correctly refreshes expiry when accessed."""
    cache = LastSeenCache(ttl=2, sweep_interval=1)

    assert cache.add(MSG_1) is True
    assert cache.has(MSG_1) is True

    await trio.sleep(2.5)  # Wait past TTL

    # Retry loop to ensure sweep happens
    for _ in range(10):  # Up to 1 second extra
        if not cache.has(MSG_1):
            break
        await trio.sleep(0.1)

    assert cache.has(MSG_1) is False  # Should be expired

    cache.stop()


@pytest.mark.trio
async def test_timed_cache_expiry():
    """Test expiry behavior in FirstSeenCache and LastSeenCache."""
    for cache_class in [FirstSeenCache, LastSeenCache]:
        cache = cache_class(ttl=1, sweep_interval=1)

        assert cache.add(MSG_1) is True
        await trio.sleep(1.5)  # Let it expire
        assert cache.has(MSG_1) is False  # Should be expired

        cache.stop()


@pytest.mark.trio
async def test_concurrent_access():
    """Test that multiple tasks can safely access and modify the cache."""
    cache = LastSeenCache(ttl=2, sweep_interval=1)

    async def add_message(i):
        cache.add(f"msg{i}".encode())
        assert cache.has(f"msg{i}".encode()) is True

    async with trio.open_nursery() as nursery:
        for i in range(50):
            nursery.start_soon(add_message, i)

    # Ensure all elements exist before expiry
    for i in range(50):
        assert cache.has(f"msg{i}".encode()) is True

    cache.stop()


@pytest.mark.trio
async def test_timed_cache_stress_test():
    """Stress test cache by adding a large number of elements."""
    cache = FirstSeenCache(ttl=2, sweep_interval=1)

    for i in range(1000):
        assert cache.add(f"msg{i}".encode()) is True  # All should be added successfully

    # Ensure all elements exist before expiry
    for i in range(1000):
        assert cache.has(f"msg{i}".encode()) is True

    await trio.sleep(2.5)  # Wait for expiry

    # Ensure all elements have expired
    for i in range(1000):
        assert cache.has(f"msg{i}".encode()) is False

    cache.stop()


@pytest.mark.trio
async def test_expiry_removal():
    """Test that expired items are removed by the background sweeper."""
    cache = LastSeenCache(ttl=2, sweep_interval=1)
    cache.add(MSG_1)
    await trio.sleep(2.1)  # Wait for sweeper to remove expired items
    assert MSG_1 not in cache.cache  # Should be removed
    cache.stop()


@pytest.mark.trio
async def test_readding_after_expiry():
    """Test that an item can be re-added after expiry."""
    cache = FirstSeenCache(ttl=2, sweep_interval=1)
    cache.add(MSG_1)
    await trio.sleep(3)  # Let it expire
    assert cache.add(MSG_1) is True  # Should allow re-adding
    assert cache.has(MSG_1) is True
    cache.stop()


@pytest.mark.trio
async def test_multiple_adds_before_expiry():
    """Ensure multiple adds before expiry behave correctly."""
    cache = LastSeenCache(ttl=5)
    assert cache.add(MSG_1) is True
    assert cache.add(MSG_1) is False  # Second add should return False
    assert cache.has(MSG_1) is True  # Should still be in cache
    cache.stop()
