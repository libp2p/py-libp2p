import trio


class MaliciousPeer:
    """Simulates malicious behavior for attack testing"""

    def __init__(self, peer_id: str, attack_type: str, intensity: float):
        self.peer_id = peer_id
        self.attack_type = attack_type  # "eclipse", "sybil", etc.
        self.intensity = intensity
        self.poisoned_entries: dict[str, str] = {}
        self.victim_peer_table: list[str] = []

    async def poison_dht_entries(self, target_peer_id: str):
        """Poison DHT with fake entries for target peer"""
        await trio.sleep(self.intensity * 0.1)
        self.poisoned_entries[target_peer_id] = "fake_entry"

    async def flood_peer_table(self, victim_peer_table: list[str]):
        """Flood victim's peer table with malicious entries"""
        for i in range(int(self.intensity * 10)):
            victim_peer_table.append(f"malicious_{i}")
            await trio.sleep(0.01)
