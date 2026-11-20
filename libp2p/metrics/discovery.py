from prometheus_client import Counter, Histogram

from libp2p.discovery.events.events import DiscoveryEvent


class DiscoveryMetrics:
    """Prometheus metrics for the peer discovery modules (bounded labels only)."""

    peer_discovered: Counter
    peer_lost: Counter
    bootstrap_connect: Counter
    bootstrap_connect_duration_ms: Histogram
    random_walk: Counter
    random_walk_peers_found: Histogram

    def __init__(self) -> None:
        self.peer_discovered = Counter(
            "discovery_peer_discovered_total",
            "Peers discovered by the discovery modules",
            labelnames=["source"],
        )
        self.peer_lost = Counter(
            "discovery_peer_lost_total",
            "Peers lost/expired by the discovery modules",
            labelnames=["source"],
        )
        self.bootstrap_connect = Counter(
            "discovery_bootstrap_connect_total",
            "Bootstrap connect attempts",
            labelnames=["result"],
        )
        self.bootstrap_connect_duration_ms = Histogram(
            "discovery_bootstrap_connect_duration_ms",
            "Bootstrap connect duration in milliseconds",
            buckets=[10, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
        )
        self.random_walk = Counter(
            "discovery_random_walk_total",
            "Random walk operations",
            labelnames=["result"],
        )
        self.random_walk_peers_found = Histogram(
            "discovery_random_walk_peers_found",
            "Peers found per random walk",
            buckets=[1, 2, 5, 10, 20, 50],
        )

    def record(self, event: DiscoveryEvent) -> None:
        if event.peer_discovered:
            self.peer_discovered.labels(source=event.source or "unknown").inc()
        elif event.peer_lost:
            self.peer_lost.labels(source=event.source or "unknown").inc()
        elif event.bootstrap_connect:
            result = "success" if event.success else "failure"
            self.bootstrap_connect.labels(result=result).inc()
            if event.duration_ms is not None:
                self.bootstrap_connect_duration_ms.observe(event.duration_ms)
        elif event.random_walk:
            result = "success" if event.success else "failure"
            self.random_walk.labels(result=result).inc()
            if event.peers_found is not None:
                self.random_walk_peers_found.observe(event.peers_found)
