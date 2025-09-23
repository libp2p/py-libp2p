from typing import List, Dict

class NetworkMonitor:
    """Monitor network state"""

    def __init__(self):
        self.peer_status: Dict[str, str] = {}

    def set_peer_status(self, peer_id: str, status: str):
        self.peer_status[peer_id] = status

    def get_online_peers(self) -> List[str]:
        return [p for p,s in self.peer_status.items() if s == "online"]
