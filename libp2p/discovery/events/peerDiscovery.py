from collections.abc import (
    Awaitable,
    Callable,
)

import trio

from libp2p.abc import (
    PeerInfo,
)

TTL: int = 60 * 60  # Time-to-live for discovered peers in seconds


class PeerDiscovery:
    def __init__(self) -> None:
        self._peer_discovered_handlers: list[Callable[[PeerInfo], Awaitable[None]]] = []

    def register_peer_discovered_handler(
        self, handler: Callable[[PeerInfo], Awaitable[None]]
    ) -> None:
        self._peer_discovered_handlers.append(handler)

    async def emit_peer_discovered(self, peer_info: PeerInfo) -> None:
        for handler in self._peer_discovered_handlers:
            await handler(peer_info)


peerDiscovery = PeerDiscovery()


async def peerDiscoveryHandler(peerInfo: PeerInfo) -> None:
    await trio.sleep(5)  # Simulate some processing delay
    # print("Discovered peer is", peerInfo.peer_id)


peerDiscovery.register_peer_discovered_handler(peerDiscoveryHandler)
