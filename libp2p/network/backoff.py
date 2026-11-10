import time

from multiaddr import Multiaddr

from libp2p.peer.id import ID


class DialBackoff:
    """
    Quadratic per-address dial backoff, matching go-libp2p's DialBackoff.

    Used to avoid over-dialing the same dead peers and addresses. When an
    address fails or times out, it is added to DialBackoff. Subsequent dials
    to that address check for backoff and exit promptly without opening sockets.
    If a dial succeeds, the peer and all its addresses are cleared from backoff.

    Formula: min(BackoffBase + BackoffCoef * tries^2, BackoffMax)
    Default: BackoffBase = 5.0s, BackoffCoef = 1.0s, BackoffMax = 300.0s (5m).
    """

    def __init__(
        self,
        base: float = 5.0,
        coef: float = 1.0,
        max_backoff: float = 300.0,
        max_entries: int = 10000,
    ) -> None:
        self.base = base
        self.coef = coef
        self.max_backoff = max_backoff
        self.max_entries = max_entries
        # (peer_id_str, addr_str) -> (tries: int, until: float)
        self._entries: dict[tuple[str, str], tuple[int, float]] = {}

    def is_backed_off(self, peer_id: ID | str, addr: Multiaddr | str) -> bool:
        """Return True if this address for the peer is currently in backoff."""
        key = (str(peer_id), str(addr))
        entry = self._entries.get(key)
        if entry is None:
            return False
        _tries, until = entry
        now = time.monotonic()
        if now < until:
            return True
        # Expired: remove and return False
        del self._entries[key]
        return False

    def add_backoff(self, peer_id: ID | str, addr: Multiaddr | str) -> None:
        """
        Record a failed dial attempt to an address and calculate its next backoff
        expiry.
        """
        if len(self._entries) >= self.max_entries:
            self.cleanup()
            if len(self._entries) >= self.max_entries:
                # Evict oldest entry
                oldest_key = min(self._entries, key=lambda k: self._entries[k][1])
                del self._entries[oldest_key]

        key = (str(peer_id), str(addr))
        now = time.monotonic()
        entry = self._entries.get(key)
        if entry is None:
            tries = 1
        else:
            tries = entry[0] + 1

        backoff_duration = min(
            self.base + self.coef * (tries * tries), self.max_backoff
        )
        self._entries[key] = (tries, now + backoff_duration)

    def clear(self, peer_id: ID | str) -> None:
        """Clear backoff records for all addresses of a peer after a successful dial."""
        pid_str = str(peer_id)
        keys_to_del = [k for k in self._entries if k[0] == pid_str]
        for k in keys_to_del:
            del self._entries[k]

    def cleanup(self) -> None:
        """Prune expired backoff entries to keep memory bounded."""
        now = time.monotonic()
        expired = [k for k, (_tries, until) in self._entries.items() if now >= until]
        for k in expired:
            del self._entries[k]
