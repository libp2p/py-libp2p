from __future__ import annotations

import hashlib

from libp2p.custom_types import TProtocol

FIL_HELLO_PROTOCOL = TProtocol("/fil/hello/1.0.0")
FIL_CHAIN_EXCHANGE_PROTOCOL = TProtocol("/fil/chain/xchg/0.0.1")

FIL_BLOCKS_TOPIC_PREFIX = "/fil/blocks"
FIL_MESSAGES_TOPIC_PREFIX = "/fil/msgs"
FIL_DHT_PROTOCOL_PREFIX = "/fil/kad"

GOSSIP_SCORE_THRESHOLD = -500.0
PUBLISH_SCORE_THRESHOLD = -1000.0
GRAYLIST_SCORE_THRESHOLD = -2500.0
ACCEPT_PX_SCORE_THRESHOLD = 1000.0
OPPORTUNISTIC_GRAFT_SCORE_THRESHOLD = 3.5


def blocks_topic(network_name: str) -> str:
    return FIL_BLOCKS_TOPIC_PREFIX + "/" + network_name


def messages_topic(network_name: str) -> str:
    return FIL_MESSAGES_TOPIC_PREFIX + "/" + network_name


def dht_protocol_name(network_name: str) -> TProtocol:
    return TProtocol(FIL_DHT_PROTOCOL_PREFIX + "/" + network_name)


def filecoin_message_id(msg: object) -> bytes:
    """Expect ``msg`` to expose a bytes-like ``data`` attribute."""
    data = getattr(msg, "data", None)
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("message 'data' field must be bytes-like")
    return hashlib.blake2b(bytes(data), digest_size=32).digest()
