#!/usr/bin/env python3
"""
WebRTC Interop Test Runner

Orchestrates testing between different libp2p implementations using Redis
for coordination and signaling.
"""

from datetime import datetime
import logging
import sys

import redis.asyncio as redis  # type: ignore[import-untyped]
import trio
from trio_asyncio import aio_as_trio, open_loop  # type: ignore[import-untyped]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class WebRTCTestRunner:
    """Orchestrates WebRTC interop tests via Redis coordination"""

    def __init__(self, redis_url: str = "redis://localhost:6379", timeout: int = 30):
        self.redis_url = redis_url
        self.redis_client: redis.Redis | None = None
        self.timeout = timeout
        self.test_results: dict[str, bool] = {}

    async def connect(self):
        """Connect to Redis"""
        try:
            self.redis_client = await aio_as_trio(redis.from_url(self.redis_url))
            logger.info("Connecting to Redis at %s", self.redis_url)
            await aio_as_trio(self.redis_client.ping())
            logger.info("✓ Redis connection successful")
        except Exception as e:
            logger.error("✗ Failed to connect to Redis: %s", e)
            raise

    async def clear_state(self):
        """Clear previous test data from Redis"""
        try:
            logger.info("Clearing previous test data from Redis...")
            keys = await aio_as_trio(self.redis_client.keys("interop:webrtc:*"))
            if keys:
                await aio_as_trio(self.redis_client.delete(*keys))
                logger.info("✓ Redis state cleared (%d keys removed)", len(keys))
        except Exception as e:
            logger.error("✗ Failed to clear Redis state: %s", e)
            raise

    async def wait_for_key(self, key: str, timeout: int | None = None) -> bool:
        """Wait for a Redis key to exist within timeout"""
        if timeout is None:
            timeout = self.timeout

        start = datetime.now()
        check_interval = 0.1

        while (datetime.now() - start).total_seconds() < timeout:
            try:
                exists = await aio_as_trio(self.redis_client.exists(key))
                if exists:
                    value = await aio_as_trio(self.redis_client.get(key))
                    value_str = value.decode("utf-8") if value else "(empty)"
                    logger.info("  ✓ Key '%s' is ready: %s", key, value_str)
                    return True
            except Exception as e:
                logger.error("  ✗ Error checking key: %s", e)
                return False

            await trio.sleep(check_interval)

        elapsed = (datetime.now() - start).total_seconds()
        logger.error("  ✗ Timeout waiting for '%s' (%.1f seconds)", key, elapsed)
        return False

    async def get_redis_value(self, key: str) -> str | None:
        """Get value from Redis"""
        try:
            value = await aio_as_trio(self.redis_client.get(key))
            return value.decode("utf-8") if value else None
        except Exception as e:
            logger.error("Error getting key '%s': %s", key, e)
            return None

    async def test_py_listener_go_dialer(self):
        """Test: Python listener <-> Go dialer"""
        logger.info("=" * 70)
        logger.info("TEST 1: py-libp2p listener <-> go-libp2p dialer")
        logger.info("=" * 70)

        try:
            # Step 1: Wait for Python listener
            logger.info("Step 1: Waiting for Python listener to start...")
            if not await self.wait_for_key(
                "interop:webrtc:listener:ready", self.timeout
            ):
                logger.error("FAILED: Python listener never started")
                return False

            # Step 2: Verify SDP offer exists
            logger.info("Step 2: Verifying SDP offer...")
            listener_offer = await self.get_redis_value("interop:webrtc:listener:offer")
            if not listener_offer:
                logger.error("FAILED: Listener SDP offer not found in Redis")
                return False
            logger.info("  SDP offer length: %d bytes", len(listener_offer))

            # Step 3: Wait for Go dialer to process
            logger.info("Step 3: Waiting for Go dialer to process...")
            await trio.sleep(2)  # Give dialer time to start and detect Python listener

            # Step 4: Wait for connection (signaling layer)
            logger.info("Step 4: Waiting for connection signal...")
            if not await self.wait_for_key(
                "interop:webrtc:dialer:connected", self.timeout
            ):
                logger.error("FAILED: Go dialer never signaled connection")
                return False

            # Step 5: Wait for ping
            logger.info("Step 5: Waiting for ping success signal...")
            if not await self.wait_for_key("interop:webrtc:ping:success", self.timeout):
                logger.error("FAILED: Ping test failed")
                return False

            logger.info("✓ TEST PASSED: py-listener-go-dialer (signaling layer)")
            return True

        except Exception as e:
            logger.error("✗ TEST FAILED with exception: %s", e, exc_info=True)
            return False

    async def test_go_listener_py_dialer(self):
        """Test: Go listener <-> Python dialer"""
        logger.info("=" * 70)
        logger.info("TEST 2: go-libp2p listener <-> py-libp2p dialer")
        logger.info("=" * 70)

        try:
            # Step 1: Wait for Go listener
            logger.info("Step 1: Waiting for Go listener to start...")
            if not await self.wait_for_key(
                "interop:webrtc:go:listener:ready", self.timeout
            ):
                logger.error("FAILED: Go listener never started")
                return False

            # Step 2: Get Go listener multiaddr
            logger.info("Step 2: Getting Go listener multiaddr...")
            go_multiaddr = await self.get_redis_value(
                "interop:webrtc:go:listener:multiaddr"
            )
            if not go_multiaddr:
                logger.error("FAILED: Go listener multiaddr not found in Redis")
                return False
            logger.info("  Go listener multiaddr: %s", go_multiaddr)

            # Step 3: Signal Python dialer
            logger.info("Step 3: Signaling Python dialer to connect...")
            await aio_as_trio(
                self.redis_client.set("interop:webrtc:py:connect", go_multiaddr)
            )

            # Step 4: Wait for connection
            logger.info("Step 4: Waiting for Python dialer to connect...")
            if not await self.wait_for_key(
                "interop:webrtc:py:dialer:connected", self.timeout
            ):
                logger.error("FAILED: Python dialer never connected")
                return False

            # Step 5: Wait for ping
            logger.info("Step 5: Waiting for ping/pong test...")
            if not await self.wait_for_key(
                "interop:webrtc:py:ping:success", self.timeout
            ):
                logger.error("FAILED: Ping/pong test failed")
                return False

            logger.info("✓ TEST PASSED: go-listener-py-dialer")
            return True

        except Exception as e:
            logger.error("✗ TEST FAILED with exception: %s", e, exc_info=True)
            return False

    async def print_report(self) -> bool:
        """Print test report"""
        logger.info("=" * 70)
        logger.info("WEBRTC INTEROP TEST REPORT")
        logger.info("=" * 70)

        passed = sum(1 for v in self.test_results.values() if v)
        total = len(self.test_results)

        for test_name, result in self.test_results.items():
            status = "✓ PASSED" if result else "✗ FAILED"
            logger.info("  %s: %s", test_name, status)

        logger.info("-" * 70)
        logger.info(
            "Total: %d | Passed: %d | Failed: %d", total, passed, total - passed
        )
        logger.info("=" * 70)

        if passed == total:
            logger.info("✓ ALL TESTS PASSED!")
            return True
        else:
            logger.error("✗ SOME TESTS FAILED")
            return False

    async def run_all_tests(self) -> bool:
        """Run all interop tests"""
        logger.info("\n")
        logger.info("╔" + "=" * 68 + "╗")
        logger.info("║" + " " * 20 + "WebRTC Interop Test Suite" + " " * 23 + "║")
        logger.info("╚" + "=" * 68 + "╝\n")

        try:
            await self.connect()
            await self.clear_state()

            # Test 1: Python listener, Go dialer
            self.test_results[
                "py-listener-go-dialer"
            ] = await self.test_py_listener_go_dialer()

            await trio.sleep(2)
            await self.clear_state()

            # Test 2: Go listener, Python dialer
            self.test_results[
                "go-listener-py-dialer"
            ] = await self.test_go_listener_py_dialer()

            # Print report
            success = await self.print_report()
            return success

        except Exception as e:
            logger.error("✗ Test runner fatal error: %s", e, exc_info=True)
            return False
        finally:
            if self.redis_client:
                await aio_as_trio(self.redis_client.aclose())


async def main() -> bool:
    """Main entry point"""
    runner = WebRTCTestRunner(timeout=30)
    success = await runner.run_all_tests()
    return success


if __name__ == "__main__":

    async def run_with_redis() -> None:
        async with open_loop():
            success = await main()
            sys.exit(0 if success else 1)

    trio.run(run_with_redis)
