import logging

import trio

logging.basicConfig(level=logging.INFO)
from libp2p.network.auto_connector import AutoConnector
from libp2p.network.config import ConnectionConfig


class MockPeerStore:
    def peer_ids(self): return []

class MockSwarm:
    def __init__(self):
        self.connection_config = ConnectionConfig(low_watermark=300)
        self.peerstore = MockPeerStore()
    def get_total_connections(self): return 5

async def main():
    swarm = MockSwarm()
    ac = AutoConnector(swarm)
    await ac.start()
    await ac.maybe_connect()

trio.run(main)
