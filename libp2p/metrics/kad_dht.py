from prometheus_client import Counter, Gauge, Histogram

from libp2p.kad_dht.events import KadDhtEvent


class KadDhtMetrics:
    inbound: Counter
    find_node: Counter
    get_value: Counter
    put_value: Counter
    get_providers: Counter
    add_provider: Counter

    # Outbound / operational
    lookup_total: Counter
    lookup_duration_ms: Histogram
    lookup_peers_queried: Histogram
    lookup_peers_found: Histogram
    provide_total: Counter
    provide_peers_announced: Histogram
    find_providers_total: Counter
    find_providers_found: Histogram
    put_value_out_total: Counter
    get_value_out_total: Counter
    find_peer_total: Counter
    refresh_total: Counter
    republish_total: Counter
    rate_limited_total: Counter
    stream_reset_total: Counter
    routing_table_peers: Gauge

    def __init__(self) -> None:
        self.inbound = Counter(
            "kad_inbound_total",
            "Total inbound requests received",
        )

        self.find_node = Counter(
            "kad_inbound_find_node",
            "Total inbound FIND_NODE requests received",
        )

        self.get_value = Counter(
            "kad_inbound_get_value",
            "Total inbound GET_VALUE requests received",
        )

        self.put_value = Counter(
            "kad_inbound_put_value",
            "Total inbound PUT_VALUE requests received",
        )

        self.get_providers = Counter(
            "kad_inbound_get_providers",
            "Total inbound GET_PROVIDERS requests received",
        )

        self.add_provider = Counter(
            "kad_inbound_add_provider",
            "Total inbound ADD_PROVIDER requests received",
        )

        # Outbound lookups (iterative FIND_NODE)
        self.lookup_total = Counter(
            "kad_lookup_total",
            "Iterative peer lookups performed",
            labelnames=["result"],
        )
        self.lookup_duration_ms = Histogram(
            "kad_lookup_duration_ms",
            "Iterative lookup duration in milliseconds",
            buckets=[10, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000],
        )
        self.lookup_peers_queried = Histogram(
            "kad_lookup_peers_queried",
            "Peers queried per iterative lookup",
            buckets=[1, 2, 5, 10, 20, 50, 100],
        )
        self.lookup_peers_found = Histogram(
            "kad_lookup_peers_found",
            "Peers found per iterative lookup",
            buckets=[1, 2, 5, 10, 20, 50, 100],
        )

        # Content providing
        self.provide_total = Counter(
            "kad_provide_total",
            "Content provide announcements",
            labelnames=["result"],
        )
        self.provide_peers_announced = Histogram(
            "kad_provide_peers_announced",
            "Peers announced to per provide call",
            buckets=[1, 2, 5, 10, 20, 50],
        )

        # Provider discovery
        self.find_providers_total = Counter(
            "kad_find_providers_total",
            "Provider lookups performed",
            labelnames=["result"],
        )
        self.find_providers_found = Histogram(
            "kad_find_providers_found",
            "Providers found per lookup",
            buckets=[1, 2, 5, 10, 20, 50],
        )

        # Value storage / retrieval
        self.put_value_out_total = Counter(
            "kad_put_value_total",
            "Value store operations (outbound)",
            labelnames=["result"],
        )
        self.get_value_out_total = Counter(
            "kad_get_value_total",
            "Value retrieve operations (outbound)",
            labelnames=["result"],
        )

        # Peer routing
        self.find_peer_total = Counter(
            "kad_find_peer_total",
            "Peer lookup operations",
            labelnames=["result"],
        )

        # Maintenance
        self.refresh_total = Counter(
            "kad_refresh_total",
            "Routing table refresh cycles",
            labelnames=["result"],
        )
        self.republish_total = Counter(
            "kad_republish_total",
            "Record republish operations",
            labelnames=["type", "result"],
        )

        # Operational / defensive
        self.rate_limited_total = Counter(
            "kad_rate_limited_total",
            "Inbound requests rejected by rate limiting",
        )
        self.stream_reset_total = Counter(
            "kad_stream_reset_total",
            "DHT streams reset due to protocol violations",
        )
        self.routing_table_peers = Gauge(
            "kad_routing_table_peers",
            "Number of peers currently in the routing table",
        )
        self.record_validation_total = Counter(
            "kad_record_validation_total",
            "Record validation outcomes (namespace validate/select)",
            labelnames=["type", "result"],
        )

    def record(self, event: KadDhtEvent) -> None:
        if event.inbound:
            self.inbound.inc()

        if event.find_node:
            self.find_node.inc()

        if event.get_value:
            self.get_value.inc()

        if event.put_value:
            self.put_value.inc()

        if event.get_providers:
            self.get_providers.inc()

        if event.add_provider:
            self.add_provider.inc()

        if event.lookup:
            result = "success" if event.success else "failure"
            self.lookup_total.labels(result=result).inc()
            if event.duration_ms is not None:
                self.lookup_duration_ms.observe(event.duration_ms)
            if event.peers_queried is not None:
                self.lookup_peers_queried.observe(event.peers_queried)
            if event.peers_found is not None:
                self.lookup_peers_found.observe(event.peers_found)

        if event.provide:
            result = "success" if event.success else "failure"
            self.provide_total.labels(result=result).inc()
            if event.peers_announced is not None:
                self.provide_peers_announced.observe(event.peers_announced)

        if event.find_providers:
            result = "success" if event.success else "failure"
            self.find_providers_total.labels(result=result).inc()
            if event.providers_found is not None:
                self.find_providers_found.observe(event.providers_found)

        if event.put_value_out:
            result = "success" if event.success else "failure"
            self.put_value_out_total.labels(result=result).inc()

        if event.get_value_out:
            result = "success" if event.success else "failure"
            self.get_value_out_total.labels(result=result).inc()

        if event.find_peer:
            result = "success" if event.success else "failure"
            self.find_peer_total.labels(result=result).inc()

        if event.refresh:
            result = "success" if event.success else "failure"
            self.refresh_total.labels(result=result).inc()

        if event.republish:
            result = "success" if event.success else "failure"
            self.republish_total.labels(
                type=event.record_type or "unknown", result=result
            ).inc()

        if event.rate_limited:
            self.rate_limited_total.inc()

        if event.stream_reset:
            self.stream_reset_total.inc()

        if event.routing_table and event.count is not None:
            self.routing_table_peers.set(event.count)

        if event.record_validation:
            result = "success" if event.success else "failure"
            self.record_validation_total.labels(
                type=event.record_type or "unknown", result=result
            ).inc()
