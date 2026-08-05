#!/usr/bin/env python

"""
Use the grid-topology routing table through the public Kademlia DHT APIs.
"""

import logging
import secrets

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.kad_dht import DHTMode, KadDHT
from libp2p.kad_dht.grid_routing_table import GridRoutingTable
from libp2p.peer.peerinfo import PeerInfo
from libp2p.tools.anyio_service import background_trio_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("grid-topology-example")


def make_host(port: int):
    key_pair = create_new_key_pair(secrets.token_bytes(32))
    return new_host(key_pair=key_pair), [Multiaddr(f"/ip4/127.0.0.1/tcp/{port}")]


async def main() -> None:
    host_a, listen_a = make_host(0)
    host_b, listen_b = make_host(0)

    async with (
        host_a.run(listen_addrs=listen_a),
        host_b.run(listen_addrs=listen_b),
        background_trio_service(
            KadDHT(host_a, DHTMode.SERVER, routing_table_type="grid")
        ) as dht_a,
        background_trio_service(
            KadDHT(host_b, DHTMode.SERVER, routing_table_type="grid")
        ) as dht_b,
    ):
        peer_b_info = PeerInfo(host_b.get_id(), host_b.get_addrs())

        added = await dht_a.add_peer(peer_b_info, skip_server_mode_check=True)
        closest = await dht_a.peer_routing.find_closest_peers(
            host_b.get_id().to_bytes(),
            count=1,
        )

        logger.info(
            "Grid table enabled: %s",
            isinstance(dht_a.routing_table, GridRoutingTable),
        )
        logger.info("Peer added through KadDHT.add_peer: %s", added)
        logger.info("Routing table size: %s", dht_a.get_routing_table_size())
        logger.info(
            "Closest peer lookup returned host_b: %s",
            host_b.get_id() in closest,
        )
        logger.info("Second DHT is running with peer id: %s", dht_b.host.get_id())


if __name__ == "__main__":
    trio.run(main)
