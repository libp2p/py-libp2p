"""
Event definitions for the peer discovery modules.

Emitted on the host's event bus whenever a discovery module observes
something: a peer is discovered or lost via mDNS/bootstrap/random-walk,
a bootstrap connect attempt completes, a random walk finishes.

The app-facing ``peerDiscovery`` singleton (``peerDiscovery.py``) is
unaffected — these events are the observability side of the same
occurrences.
"""


class DiscoveryEvent:
    """
    A discovery event, emitted on the host's event bus.

    One event object carries a single occurrence; boolean flags mark which
    kind of event it is and the remaining fields carry its payload.
    """

    peer_id: str | None = None

    peer_discovered: bool = False
    peer_lost: bool = False
    bootstrap_connect: bool = False
    random_walk: bool = False

    # Fields
    source: str | None = None  # mdns | bootstrap | random_walk | rendezvous
    addr_count: int | None = None
    success: bool | None = None
    duration_ms: float | None = None
    peers_found: int | None = None
    reason: str | None = None

    # Debugging details (random walk / refresh)
    target_key: str | None = None  # the random key / peer id generated for the walk
    peers: list[str] | None = None  # peer ids returned by the query (bounded)
    peers_added: int | None = None  # peers added to the routing table (refresh)
