"""
mDNS-based peer discovery for py-libp2p.
Conforms to https://github.com/libp2p/specs/blob/master/discovery/mdns.md
Uses zeroconf for mDNS broadcast/listen. Async operations use trio.
"""

import logging
from typing import Any

import trio
from zeroconf import (
    Zeroconf,
)

from libp2p.abc import (
    INetworkService,
)

from .broadcaster import (
    PeerBroadcaster,
)
from .listener import (
    PeerListener,
)
from .utils import (
    stringGen,
)

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_p2p._udp.local."
MCAST_PORT = 5353
MCAST_ADDR = "224.0.0.251"


class MDNSDiscovery:
    """
    mDNS-based peer discovery for py-libp2p, using zeroconf.

    Conforms to the libp2p mDNS discovery spec.
    Supports:
    - Spec-compliant dnsaddr TXT records
    - IPv4 and IPv6 (A and AAAA records)
    - Meta query (_services._dns-sd._udp.local)
    - Private networks (_p2p-X._udp.local)
    - Configurable TTL and retry logic
    - Async/non-blocking operation with trio
    """

    _cleanup_task: trio.lowlevel.Task | None

    def __init__(
        self,
        swarm: INetworkService,
        port: int = 4001,
        listen_addrs: list[str] | None = None,
        service_type: str | None = None,
        ttl: int = 120,
        retry_attempts: int = 3,
        retry_base_delay: float = 1.0,
        cleanup_interval: int = 60,
    ):
        self.peer_id = str(swarm.get_peer_id())
        self.port = port
        self.listen_addrs = listen_addrs or []
        self.service_type = service_type or SERVICE_TYPE
        self.ttl = ttl
        self.retry_attempts = retry_attempts
        self.retry_base_delay = retry_base_delay
        self.cleanup_interval = cleanup_interval

        self.zeroconf = Zeroconf()
        self.service_name = f"{stringGen(63)}.{self.service_type}"
        self.peerstore = swarm.peerstore
        self.swarm = swarm

        self.broadcaster = PeerBroadcaster(
            zeroconf=self.zeroconf,
            service_type=self.service_type,
            service_name=self.service_name,
            peer_id=self.peer_id,
            port=self.port,
            listen_addrs=self.listen_addrs,
        )
        self.listener = PeerListener(
            zeroconf=self.zeroconf,
            peerstore=self.peerstore,
            service_type=self.service_type,
            service_name=self.service_name,
            ttl=self.ttl,
            retry_attempts=self.retry_attempts,
            retry_base_delay=self.retry_base_delay,
        )

        self._cleanup_cancel_scope: trio.CancelScope | None = None
        self._cleanup_task: trio.lowlevel.Task | None = None

    def start(self) -> None:
        """Register this peer and start listening for others."""
        logger.debug(
            f"Starting mDNS discovery for peer {self.peer_id} on port {self.port}"
        )
        self.broadcaster.register()
        # Listener is started in constructor

        # Start periodic cleanup task with cancel scope
        self._cleanup_cancel_scope = trio.CancelScope()
        self._cleanup_task = trio.lowlevel.spawn_system_task(
            self._cleanup_loop_with_scope
        )

    async def _cleanup_loop_with_scope(self) -> None:
        """Periodic cleanup with cancel scope support."""
        assert self._cleanup_cancel_scope is not None
        with self._cleanup_cancel_scope:
            await self._cleanup_loop()

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup of stale discovered services."""
        while True:
            await trio.sleep(self.cleanup_interval)
            try:
                removed = self.listener.cleanup_stale_entries(max_age=self.ttl * 2)
                if removed > 0:
                    logger.debug(f"Cleaned up {removed} stale mDNS entries")
            except Exception as e:
                logger.warning(f"Error during mDNS cleanup: {e}")

    def stop(self) -> None:
        """Unregister this peer and clean up zeroconf resources."""
        logger.debug("Stopping mDNS discovery")
        self.broadcaster.unregister()

        if self._cleanup_cancel_scope is not None:
            self._cleanup_cancel_scope.cancel()

        self.listener.stop()
        self.zeroconf.close()


def create_mdns_discovery(
    swarm: INetworkService,
    port: int = 4001,
    listen_addrs: list[str] | None = None,
    private_network_fingerprint: str | None = None,
    ttl: int = 120,
    **kwargs: Any,
) -> MDNSDiscovery:
    """
    Factory function to create MDNSDiscovery with common options.

    Args:
        swarm: The network service
        port: Port to advertise
        listen_addrs: List of multiaddrs to advertise
        private_network_fingerprint: If set, uses _p2p-<fp>._udp.local
        ttl: TTL for discovered peer addresses (seconds)
        **kwargs: Additional options passed to MDNSDiscovery

    Returns:
        Configured MDNSDiscovery instance

    """
    service_type = SERVICE_TYPE
    if private_network_fingerprint:
        # Private network: _p2p-<fingerprint>._udp.local
        service_type = f"_p2p-{private_network_fingerprint}._udp.local."

    return MDNSDiscovery(
        swarm=swarm,
        port=port,
        listen_addrs=listen_addrs,
        service_type=service_type,
        ttl=ttl,
        **kwargs,
    )
