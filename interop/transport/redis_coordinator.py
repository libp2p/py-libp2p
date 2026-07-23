from __future__ import annotations

import logging
import trio
import redis.asyncio as redis

logger = logging.getLogger("libp2p.interop.redis")

class RedisCoordinator:
    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._client: redis.Redis | None = None

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = await self._connect_with_retry()
        return self._client

    async def _connect_with_retry(self) -> redis.Redis:
        deadline = trio.current_time() + self.timeout
        last_err = None
        while trio.current_time() < deadline:
            try:
                client = redis.Redis(host=self.host, port=self.port, decode_responses=True)
                await client.ping()
                return client
            except redis.RedisError as e:
                last_err = e
                await trio.sleep(1)
        raise TimeoutError(f"Failed to connect to redis: {last_err}")

    async def publish(self, key: str, value: str) -> None:
        client = await self._get_client()
        logger.debug("Publishing %s to %s", value, key)
        await client.set(key, value)

    async def wait_for(self, key: str, poll_interval: float = 1.0) -> str:
        client = await self._get_client()
        deadline = trio.current_time() + self.timeout
        logger.debug("Waiting for %s", key)
        while trio.current_time() < deadline:
            val = await client.get(key)
            if val is not None:
                logger.debug("Received %s: %s", key, val)
                return val
            await trio.sleep(poll_interval)
        raise TimeoutError(f"Timeout waiting for redis key: {key}")

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
