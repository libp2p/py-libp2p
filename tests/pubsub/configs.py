from typing import NamedTuple

from libp2p.pubsub import floodsub
from libp2p.pubsub import gossipsub


FLOODSUB_PROTOCOL_ID = floodsub.PROTOCOL_ID
GOSSIPSUB_PROTOCOL_ID = gossipsub.PROTOCOL_ID


class GossipsubParams(NamedTuple):
    degree: int = 10
    degree_low: int = 9
    degree_high: int = 11
    time_to_live: int = 30
    gossip_window: int = 3
    gossip_history: int = 5
    heartbeat_interval: float = 0.5


GOSSIPSUB_PARAMS = GossipsubParams()
