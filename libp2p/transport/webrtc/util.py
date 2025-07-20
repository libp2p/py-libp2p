from collections.abc import Callable
import json
import logging
import random
from typing import (
    Any,
)

import trio

from libp2p.abc import (
    IHost,
    TProtocol,
)
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub

from .gen_certificate import (
    WebRTCCertificate,
)

log = logging.getLogger("libp2p.transport.webrtc")


def pick_random_ice_servers(
    ice_servers: list[dict[str, Any]], num_servers: int = 4
) -> list[dict[str, Any]]:
    """Select a random subset of ICE servers for load distribution."""
    random.shuffle(ice_servers)
    return ice_servers[:num_servers]


def generate_ufrag(length: int = 4) -> str:
    """Generate a random username fragment (ufrag) for SDP munging."""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
    return "".join(random.choices(alphabet, k=length))


SUCCESS_CODE = 0
FAILURE_CODE = 1


class UtilsError(Exception):
    """Utility-specific error handler."""

    pass


class SDPMunger:
    """Handle SDP modification for direct connections"""

    @staticmethod
    def munge_offer(sdp: str, ip: str, port: int) -> str:
        """Modify SDP offer for direct connection"""
        lines = sdp.split("\n")
        munged = []

        for line in lines:
            if line.startswith("a=candidate"):
                # Modify ICE candidate to use provided IP/port
                parts = line.split()
                parts[4] = ip
                parts[5] = str(port)
                line = " ".join(parts)
            munged.append(line)

        return "\n".join(munged)

    @staticmethod
    def munge_answer(sdp: str, ip: str, port: int) -> str:
        """Modify SDP answer for direct connection"""
        return SDPMunger.munge_offer(sdp, ip, port)


class WebRTCDirectDiscovery:
    """Peer discovery mechanism for WebRTC-Direct connections"""

    def __init__(self, host: IHost, cert_mgr: WebRTCCertificate) -> None:
        self.host = host
        self.cert_mgr = cert_mgr
        self.pubsub: Pubsub | None = None
        self.discovered_peers: dict[str, dict[str, Any]] = {}
        self.discovery_callbacks: list[Callable[[str, dict[str, Any]], Any]] = []

    async def start_discovery(self) -> None:
        """Start peer discovery using libp2p pubsub"""
        if not self.pubsub:
            gossipsub = GossipSub(
                protocols=[TProtocol("/libp2p/webrtc-direct/discovery/1.0.0")],
                degree=10,
                degree_low=3,
                degree_high=15,
            )
            self.pubsub = Pubsub(self.host, gossipsub, None)

        # Subscribe to discovery topic
        discovery_topic = await self.pubsub.subscribe("webrtc-direct-discovery")

        async def handle_discovery_message() -> None:
            async for msg in discovery_topic:
                try:
                    data = json.loads(msg.data.decode())
                    await self._handle_peer_announcement(data, str(msg.from_id))
                except Exception as e:
                    log.error(f"Error handling discovery message: {e}")

        async with trio.open_nursery() as nursery:
            nursery.start_soon(handle_discovery_message)
            await self._announce_presence()
            log.info("WebRTC-Direct peer discovery started")

    async def _announce_presence(self) -> None:
        """Announce our presence for WebRTC-Direct connections"""
        announcement = {
            "type": "peer_announcement",
            "peer_id": str(self.host.get_id()),
            "certhash": self.cert_mgr.certhash,
            "protocols": ["webrtc-direct"],
            "timestamp": trio.current_time(),
        }

        if self.pubsub is not None:
            await self.pubsub.publish(
                "webrtc-direct-discovery", json.dumps(announcement).encode()
            )
            log.debug(f"Announced WebRTC-Direct presence: {self.host.get_id()}")

    async def _handle_peer_announcement(
        self, data: dict[str, Any], sender_peer_id: str
    ) -> None:
        """Handle incoming peer announcements"""
        if data.get("type") == "peer_announcement":
            peer_id = data.get("peer_id")
            certhash = data.get("certhash")
            protocols = data.get("protocols", [])

            if "webrtc-direct" in protocols and peer_id != str(self.host.get_id()):
                if isinstance(peer_id, str):
                    self.discovered_peers[peer_id] = {
                        "certhash": certhash,
                        "protocols": protocols,
                        "last_seen": trio.current_time(),
                    }
                    log.info(f"Discovered WebRTC-Direct peer: {peer_id}")

                    # Notify discovery callbacks
                    for callback in self.discovery_callbacks:
                        try:
                            await callback(peer_id, data)
                        except Exception as e:
                            log.error(f"Discovery callback error: {e}")

    def add_discovery_callback(
        self, callback: Callable[[str, dict[str, Any]], Any]
    ) -> None:
        """Add callback for peer discovery events"""
        self.discovery_callbacks.append(callback)

    def get_discovered_peers(self) -> dict[str, dict[str, Any]]:
        """Get list of discovered peers"""
        current_time = trio.current_time()
        for peer_id in list(self.discovered_peers.keys()):
            last_seen = self.discovered_peers[peer_id].get("last_seen")
            if isinstance(last_seen, (int, float)) and current_time - last_seen > 300:
                del self.discovered_peers[peer_id]

        return self.discovered_peers.copy()
