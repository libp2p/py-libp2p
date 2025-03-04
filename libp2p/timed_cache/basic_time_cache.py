import threading
import time


class TimedCache:
    """Base class for Timed Cache with cleanup mechanism."""

    cache: dict[bytes, int]

    SWEEP_INTERVAL = 60  # 1-minute interval between each sweep

    def __init__(self, ttl: int) -> None:
        """
        Initialize a new TimedCache with a time-to-live for cache entries

        :param ttl: no of seconds as time-to-live for each cache entry
        """
        self.ttl = ttl
        self.lock = threading.Lock()
        self.cache = {}
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._background_cleanup, daemon=True)
        self._thread.start()

    def _background_cleanup(self) -> None:
        while not self._stop_event.wait(self.SWEEP_INTERVAL):
            self._sweep()

    def _sweep(self) -> None:
        """Removes expired entries from the cache."""
        now = time.time()
        with self.lock:
            keys_to_remove = [key for key, expiry in self.cache.items() if expiry < now]
            for key in keys_to_remove:
                del self.cache[key]

    def stop(self) -> None:
        """Stops the background cleanup thread."""
        self._stop_event.set()
        self._thread.join()

    def length(self) -> int:
        return len(self.cache)

    def add(self, key: bytes) -> bool:
        """To be implemented in subclasses."""
        raise NotImplementedError

    def has(self, key: bytes) -> bool:
        """To be implemented in subclasses."""
        raise NotImplementedError
