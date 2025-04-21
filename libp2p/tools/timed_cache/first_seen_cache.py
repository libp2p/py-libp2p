import time

from .base_timed_cache import (
    BaseTimedCache,
)


class FirstSeenCache(BaseTimedCache):
    """Cache where expiry is set only when first added."""

    def add(self, key: bytes) -> bool:
        now = int(time.time())
        with self.lock:
            if key in self.cache:
                # Check if the key is expired
                if self.cache[key] <= now:
                    # Key is expired, update the expiry and treat as a new entry
                    self.cache[key] = now + self.ttl
                    return True
                return False
            self.cache[key] = now + self.ttl
            return True

    def has(self, key: bytes) -> bool:
        now = int(time.time())
        with self.lock:
            if key in self.cache:
                # Check if key is expired
                if self.cache[key] <= now:
                    return False
                return True
            return False
