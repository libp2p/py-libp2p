"""
Performance and concurrency tests for the WebRTC trio-asyncio bridge.

This module specifically targets the `WebRTCAsyncBridge` to ensure it can handle
high concurrency and load, validating that the integration between trio and
asyncio remains stable under pressure.
"""

import asyncio
import logging
import time

import pytest
from aiortc import RTCConfiguration, RTCPeerConnection
import trio

from libp2p.transport.webrtc.async_bridge import (
    get_webrtc_bridge,
)

logger = logging.getLogger("libp2p.transport.webrtc.test_async_bridge_perf")

# Test configuration
CONCURRENCY_LEVEL = 100  # Number of concurrent connections to simulate
TEST_TIMEOUT = 60.0  # Overall timeout for the test suite


@pytest.fixture
def bridge():
    """Fixture to provide a fresh WebRTCAsyncBridge instance."""
    return get_webrtc_bridge()


@pytest.mark.trio
async def test_high_concurrency_peer_connection_creation(bridge):
    """
    Test creating a large number of RTCPeerConnections concurrently.

    Verifies that the bridge doesn't deadlock or fail when multiple tasks
    request asyncio resources simultaneously.
    """
    logger.info(f"Starting concurrency test with {CONCURRENCY_LEVEL} connections")

    start_time = time.time()
    pcs = []

    async with bridge:

        async def create_pc(index: int):
            config = RTCConfiguration()
            try:
                pc = await bridge.create_peer_connection(config)
                pcs.append(pc)
                # Simulate some brief activity
                await trio.sleep(0.01)
                return pc
            except Exception as e:
                logger.error(f"Failed to create PC {index}: {e}")
                raise

        # Launch concurrent creation tasks
        async with trio.open_nursery() as nursery:
            for i in range(CONCURRENCY_LEVEL):
                nursery.start_soon(create_pc, i)

    end_time = time.time()
    duration = end_time - start_time

    assert len(pcs) == CONCURRENCY_LEVEL, (
        f"Expected {CONCURRENCY_LEVEL} PCs, got {len(pcs)}"
    )
    logger.info(
        f"Created {CONCURRENCY_LEVEL} PCs in {duration:.2f}s "
        f" ({CONCURRENCY_LEVEL / duration:.2f} ops/s)"
    )

    # Cleanup
    async with bridge:
        for pc in pcs:
            await bridge.close_peer_connection(pc)


@pytest.mark.trio
async def test_concurrent_data_channel_operations(bridge):
    """
    Test concurrent data channel creation and operations.

    Simulates a scenario where many connections are establishing data channels
    simultaneously.
    """
    pcs = []
    channels = []

    async with bridge:
        # First create PCs
        for _ in range(CONCURRENCY_LEVEL // 2):  # Slightly lower count for full flow
            config = RTCConfiguration()
            pc = await bridge.create_peer_connection(config)
            pcs.append(pc)

        logger.info(f"Created {len(pcs)} PCs for data channel test")

        async def create_channel(pc: RTCPeerConnection, index: int):
            try:
                dc = await bridge.create_data_channel(pc, f"bench-{index}")
                channels.append(dc)
                # Send some data (conceptually - send is sync but bridged)
                # Note: sending on closed/unconnected PC might warn
                #  but tests the bridge call
                try:
                    await bridge.send_data(dc, b"ping")
                except Exception:
                    # Expected to fail sending on unconnected transport,
                    # but we just want to exercise the bridge call
                    pass
            except Exception as e:
                logger.error(f"Failed channel op {index}: {e}")
                raise

        start_time = time.time()

        async with trio.open_nursery() as nursery:
            for i, pc in enumerate(pcs):
                nursery.start_soon(create_channel, pc, i)

        end_time = time.time()
        duration = end_time - start_time

        assert len(channels) == len(pcs)
        logger.info(f"Channel ops for {len(channels)} connections in {duration:.2f}s")

        # Cleanup
        for pc in pcs:
            await bridge.close_peer_connection(pc)


@pytest.mark.trio
async def test_bridge_context_switch_performance():
    """
    Benchmark the overhead of switching contexts via the bridge.

    This purely measures the `aio_as_trio` overhead in a tight loop.
    """
    bridge = get_webrtc_bridge()
    iterations = 1000

    async def dummy_coro():
        await asyncio.sleep(0)
        return True

    start_time = time.time()

    async with bridge:
        # We need to access the internal mechanism or use a public method that wraps it
        # Since we can't easily import aio_as_trio here without setup,
        #  we use a bridge method
        # that does minimal work, or we can use the bridge context to run a custom loop

        from trio_asyncio import aio_as_trio

        for _ in range(iterations):
            await aio_as_trio(dummy_coro())

    end_time = time.time()
    duration = end_time - start_time

    logger.info(f"Context switch benchmark: {iterations} iterations in {duration:.4f}s")
    logger.info(f"Average overhead: {(duration / iterations) * 1000:.4f}ms per call")

    # Assert that overhead is reasonable (e.g., < 1ms per call)
    assert (duration / iterations) < 0.001


@pytest.mark.trio
async def test_concurrent_offer_creation(bridge):
    """
    Test generating SDP offers concurrently.

    This operation involves significant internal state within aiortc.
    """
    pcs = []
    offers = []

    async with bridge:
        # Create PCs first
        for _ in range(50):
            pc = await bridge.create_peer_connection(RTCConfiguration())
            pcs.append(pc)

        async def generate_offer(pc):
            try:
                # We need at least one transceiver or data channel
                #  to generate a valid offer
                pc.addTransceiver("audio", direction="recvonly")
                offer = await bridge.create_offer(pc)
                offers.append(offer)
            except Exception as e:
                logger.error(f"Offer generation failed: {e}")

        start_time = time.time()

        async with trio.open_nursery() as nursery:
            for pc in pcs:
                nursery.start_soon(generate_offer, pc)

        end_time = time.time()
        duration = end_time - start_time

        assert len(offers) == 50
        logger.info(f"Generated 50 concurrent SDP offers in {duration:.2f}s")

        for pc in pcs:
            await bridge.close_peer_connection(pc)
