#!/usr/bin/env python3
import asyncio
import logging
import os
import sys
import time
from typing import Dict, Optional

import redis.asyncio as redis

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [test-runner] %(message)s'
)
logger = logging.getLogger("test-runner")

COORDINATION_KEY_PREFIX = "interop:webrtc"
TEST_TIMEOUT = int(os.getenv("TEST_TIMEOUT", 120))


class InteropTestRunner:
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.results = {}

    async def wait_for_status(
        self,
        key: str,
        expected: Optional[str] = None,
        timeout: int = 60
    ) -> Optional[str]:
        logger.info(f"Waiting for {key} (timeout {timeout}s)")
        start = time.time()

        while time.time() - start < timeout:
            value = await self.redis.get(key)
            if value:
                value_str = value.decode()
                logger.info(f"{key} = {value_str}")

                if expected is None or value_str == expected:
                    return value_str
                elif value_str.startswith("failed:"):
                    return value_str

            await asyncio.sleep(0.5)

        logger.error(f"Timeout waiting for {key}")
        return None

    async def clear_redis_state(self):
        logger.info("Clearing previous test data from Redis...")
        keys = [
            f"{COORDINATION_KEY_PREFIX}:listener:addr",
            f"{COORDINATION_KEY_PREFIX}:listener:ready",
            f"{COORDINATION_KEY_PREFIX}:connection:status",
            f"{COORDINATION_KEY_PREFIX}:ping:status",
        ]
        for key in keys:
            await self.redis.delete(key)
        logger.info("Redis state cleared")

    async def run_py_listener_go_dialer(self) -> Dict:
        logger.info("TEST: py-libp2p listener <-> go-libp2p dialer")

        result = {
            "name": "py-listener-go-dialer",
            "py_role": "listener",
            "go_role": "dialer",
            "status": "unknown",
            "connection": "unknown",
            "ping": "unknown",
        }

        listener_ready = await self.wait_for_status(
            f"{COORDINATION_KEY_PREFIX}:listener:ready",
            expected="1",
            timeout=30
        )

        if not listener_ready:
            result["status"] = "failed"
            result["error"] = "Listener not ready"
            return result

        connection_status = await self.wait_for_status(
            f"{COORDINATION_KEY_PREFIX}:connection:status",
            timeout=60
        )

        if not connection_status:
            result["status"] = "failed"
            result["error"] = "Connection timeout"
            return result

        result["connection"] = connection_status

        if connection_status != "connected":
            result["status"] = "failed"
            result["error"] = f"Connection failed: {connection_status}"
            return result

        ping_status = await self.wait_for_status(
            f"{COORDINATION_KEY_PREFIX}:ping:status",
            timeout=30
        )

        if not ping_status:
            result["status"] = "failed"
            result["error"] = "Ping timeout"
            return result

        result["ping"] = ping_status

        if ping_status == "passed":
            result["status"] = "passed"
        else:
            result["status"] = "failed"
            result["error"] = f"Ping failed: {ping_status}"

        return result

    async def run_tests(self):
        logger.info("Starting WebRTC interop tests")
        await self.clear_redis_state()

        result1 = await self.run_py_listener_go_dialer()
        self.results["py-listener-go-dialer"] = result1

        return self.results

    def generate_report(self):
        logger.info("WEBRTC INTEROP TEST REPORT")

        total = len(self.results)
        passed = sum(1 for r in self.results.values() if r["status"] == "passed")
        failed = total - passed

        for name, result in self.results.items():
            logger.info(f"{name}: {result['status']}")
            if result["status"] == "failed":
                logger.info(f"   Error: {result.get('error', 'Unknown')}")
            logger.info(f"   Connection: {result.get('connection')}")
            logger.info(f"   Ping: {result.get('ping')}")

        logger.info(f"Total: {total} | Passed: {passed} | Failed: {failed}")
        return passed == total


async def main():
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6379))
    redis_url = f"redis://{redis_host}:{redis_port}"

    logger.info(f"Connecting to Redis at {redis_url}")

    try:
        redis_client = await redis.from_url(redis_url, decode_responses=False)
        await redis_client.ping()
        logger.info("Redis connection successful")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        sys.exit(1)

    runner = InteropTestRunner(redis_client)

    try:
        await runner.run_tests()
        success = runner.generate_report()

        await redis_client.close()
        sys.exit(0 if success else 1)

    except Exception as e:
        logger.error(f"Test runner error: {e}", exc_info=True)
        await redis_client.close()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
