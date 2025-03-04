import time

from .basic_time_cache import (
    TimedCache,
)


class LastSeenCache(TimedCache):
    """Cache where expiry is updated on every access."""

    def add(self, key: bytes) -> bool:
        with self.lock:
            is_new = key not in self.cache
            self.cache[key] = int(time.time()) + self.ttl
            return is_new

    def has(self, key: bytes) -> bool:
        with self.lock:
            if key in self.cache:
                self.cache[key] = int(time.time()) + self.ttl
                return True
            return False
