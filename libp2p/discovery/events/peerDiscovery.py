from collections.abc import (
    Callable,
)

from libp2p.abc import (
    PeerInfo,
)

TTL: int = 60 * 60  # Time-to-live for discovered peers in seconds


class PeerDiscovery:
    def __init__(self) -> None:
        self._peer_discovered_handlers: list[Callable[[PeerInfo], None]] = []

    def register_peer_discovered_handler(
        self, handler: Callable[[PeerInfo], None]
    ) -> None:
        self._peer_discovered_handlers.append(handler)

    def unregister_peer_discovered_handler(
        self, handler: Callable[[PeerInfo], None]
    ) -> None:
        """
        Remove a previously registered peer-discovered handler.

        ``peerDiscovery`` is a module-level singleton, so without this,
        restarting an engine in the same process (or hot-reloading a service)
        would accumulate duplicate handlers and receive duplicate discovery
        callbacks.
        """
        if handler in self._peer_discovered_handlers:
            self._peer_discovered_handlers.remove(handler)

    def emit_peer_discovered(self, peer_info: PeerInfo) -> None:
        for handler in self._peer_discovered_handlers:
            handler(peer_info)


peerDiscovery = PeerDiscovery()
