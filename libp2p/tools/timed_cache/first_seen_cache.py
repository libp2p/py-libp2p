import time

from .base_timed_cache import (
    BaseTimedCache,
)


class FirstSeenCache(BaseTimedCache):
    """Cache where expiry is set only when first added."""

    def add(self, key: bytes) -> bool:
        with self.lock:
            if key in self.cache:
                return False
            self.cache[key] = int(time.time()) + self.ttl
            return True

    def has(self, key: bytes) -> bool:
        with self.lock:
            return key in self.cache
