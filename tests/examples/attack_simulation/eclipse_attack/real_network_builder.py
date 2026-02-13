"""
Real Network Builder for Eclipse Attack Simulation

This module creates actual libp2p hosts and DHT instances for realistic attack testing,
extending the simulation framework to work with real py-libp2p components.
"""

import logging

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.abc import IHost
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.kad_dht import KadDHT
from libp2p.kad_dht.kad_dht import DHTMode
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

from .malicious_peer import MaliciousPeer
from .network_builder import AttackNetworkBuilder

logger = logging.getLogger(__name__)


class RealMaliciousPeer(MaliciousPeer):
    """Real malicious peer that can manipulate actual DHT instances"""

    def __init__(self, host: IHost, dht: KadDHT, attack_type: str, intensity: float):
        super().__init__(host.get_id().to_string(), attack_type, intensity)
        self.host = host
        self.dht = dht
        self.real_poisoned_entries = {}

    async def poison_real_dht_entries(
        self, target_dht: KadDHT, fake_peer_info: PeerInfo
    ):
        """Actually poison a real DHT's routing table"""
        try:
            # Add fake peer to the target's routing table
            await target_dht.routing_table.add_peer(fake_peer_info)

            # Inject fake routing table entries
            fake_key = f"fake_route_{fake_peer_info.peer_id}"
            fake_value = f"malicious_route_{self.peer_id}".encode()
            await target_dht.put_value(fake_key, fake_value)

            self.real_poisoned_entries[fake_peer_info.peer_id.to_string()] = fake_value
            await trio.sleep(self.intensity * 0.1)

        except Exception as e:
            logger.error("DHT poisoning failed: %s", e)

    async def flood_real_peer_table(self, target_dht: KadDHT):
        """Flood a real DHT's routing table with malicious entries"""
        try:
            for i in range(int(self.intensity * 5)):  # Reduced for real testing
                # Create fake peer info
                fake_key_pair = create_new_key_pair()
                fake_peer_id = ID.from_pubkey(fake_key_pair.public_key)
                fake_addrs = [Multiaddr(f"/ip4/127.0.0.1/tcp/{8000 + i}")]

                fake_peer_info = PeerInfo(fake_peer_id, fake_addrs)
                await target_dht.routing_table.add_peer(fake_peer_info)

                await trio.sleep(0.01)

        except Exception as e:
            logger.error("Peer table flooding failed: %s", e)


class RealNetworkBuilder(AttackNetworkBuilder):
    """Builds test networks with real libp2p hosts and DHT instances"""

    async def create_real_eclipse_test_network(
        self,
        honest_nodes: int = 3,  # Start smaller for testing
        malicious_nodes: int = 1,
    ) -> tuple[list[IHost], list[KadDHT], list[RealMaliciousPeer]]:
        """
        Create a test network with real libp2p components

        Note: This is a simplified version that creates DHT instances
        but doesn't fully manage their lifecycle for testing purposes.
        """
        honest_hosts = []
        honest_dhts = []
        malicious_peers = []

        # Create honest hosts based on the parameter
        for i in range(honest_nodes):
            honest_host = new_host()
            honest_hosts.append(honest_host)

            # Create DHT instance (don't start service for this test)
            honest_dht = KadDHT(honest_host, DHTMode.SERVER, enable_random_walk=False)
            honest_dhts.append(honest_dht)

        # Create malicious hosts based on the parameter
        for i in range(malicious_nodes):
            mal_host = new_host()
            mal_dht = KadDHT(mal_host, DHTMode.SERVER, enable_random_walk=False)

            mal_peer = RealMaliciousPeer(mal_host, mal_dht, "eclipse", 0.1)
            malicious_peers.append(mal_peer)

        return honest_hosts, honest_dhts, malicious_peers

    async def _connect_nodes(self, hosts: list[IHost]):
        """Connect hosts in a simple topology"""
        # Connect each host to the next one in a ring topology
        for i in range(len(hosts)):
            # Each node connects to 2 neighbors
            for j in range(i + 1, min(i + 3, len(hosts))):
                try:
                    peer_info = PeerInfo(hosts[j].get_id(), hosts[j].get_addrs())
                    await hosts[i].connect(peer_info)
                    await trio.sleep(0.1)  # Allow connection to establish
                except Exception as e:
                    logger.error("Connection failed between %s and %s: %s", i, j, e)

    async def setup_real_attack_scenario(
        self, scenario_config: dict
    ) -> tuple[list[IHost], list[KadDHT], list[RealMaliciousPeer]]:
        """Setup a real attack scenario with configurable parameters"""
        honest_count = scenario_config.get("honest_nodes", 5)
        malicious_count = scenario_config.get("malicious_nodes", 2)

        return await self.create_real_eclipse_test_network(
            honest_count, malicious_count
        )
