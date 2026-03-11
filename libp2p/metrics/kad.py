from prometheus_client import Counter, Histogram


class KadMetrics:
    """
    Prometheus metrics for the Kademlia behaviour.
    Mirrors the Rust libp2p metrics design.
    """

    def __init__(self):
        # -------------------------
        # GetRecord metrics
        # -------------------------

        self.query_result_get_record_ok = Counter(
            "kad_query_result_get_record_ok_total",
            "Number of records returned by a successful Kademlia get record query",
        )

        self.query_result_get_record_error = Counter(
            "kad_query_result_get_record_error_total",
            "Number of failed Kademlia get record queries",
            labelnames=["error"],
        )

        # -------------------------
        # GetClosestPeers metrics
        # -------------------------

        self.query_result_get_closest_peers_ok = Histogram(
            "kad_query_result_get_closest_peers_ok",
            "Number of closest peers returned by a successful query",
            buckets=(1, 2, 4, 8, 16, 32, 64, 128, 256, 512),
        )

        self.query_result_get_closest_peers_error = Counter(
            "kad_query_result_get_closest_peers_error_total",
            "Number of failed get closest peers queries",
            labelnames=["error"],
        )

        # -------------------------
        # GetProviders metrics
        # -------------------------

        self.query_result_get_providers_ok = Histogram(
            "kad_query_result_get_providers_ok",
            "Number of providers returned by a successful query",
            buckets=(1, 2, 4, 8, 16, 32, 64, 128, 256, 512),
        )

        self.query_result_get_providers_error = Counter(
            "kad_query_result_get_providers_error_total",
            "Number of failed get providers queries",
            labelnames=["error"],
        )

        # -------------------------
        # Query statistics
        # -------------------------

        self.query_result_num_requests = Histogram(
            "kad_query_result_num_requests",
            "Number of requests started for a Kademlia query",
            labelnames=["type"],
            buckets=(1, 2, 4, 8, 16, 32, 64, 128, 256, 512),
        )

        self.query_result_num_success = Histogram(
            "kad_query_result_num_success",
            "Number of successful requests of a Kademlia query",
            labelnames=["type"],
            buckets=(1, 2, 4, 8, 16, 32, 64, 128, 256, 512),
        )

        self.query_result_num_failure = Histogram(
            "kad_query_result_num_failure",
            "Number of failed requests of a Kademlia query",
            labelnames=["type"],
            buckets=(1, 2, 4, 8, 16, 32, 64, 128, 256, 512),
        )

        self.query_result_duration = Histogram(
            "kad_query_result_duration_seconds",
            "Duration of a Kademlia query",
            labelnames=["type"],
            buckets=(0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.8, 25.6),
        )

        # -------------------------
        # Routing table updates
        # -------------------------

        self.routing_updated = Counter(
            "kad_routing_updated_total",
            "Peers added, updated, or evicted from routing table",
            labelnames=["action", "bucket"],
        )

        # -------------------------
        # inbound requests
        # -------------------------

        self.inbound_requests = Counter(
            "kad_inbound_requests_total",
            "Number of inbound requests",
            labelnames=["request"],
        )

    # -----------------------------------------------------

    def record_outbound_query(self, query_type, stats):
        self.query_result_num_requests.labels(type=query_type).observe(
            stats["num_requests"]
        )

        self.query_result_num_success.labels(type=query_type).observe(
            stats["num_success"]
        )

        self.query_result_num_failure.labels(type=query_type).observe(
            stats["num_failures"]
        )

        if stats.get("duration") is not None:
            self.query_result_duration.labels(type=query_type).observe(
                stats["duration"]
            )

    # -----------------------------------------------------

    def record_get_record_ok(self):
        self.query_result_get_record_ok.inc()

    def record_get_record_error(self, error):
        self.query_result_get_record_error.labels(error=error).inc()

    # -----------------------------------------------------

    def record_get_closest_peers_ok(self, peer_count):
        self.query_result_get_closest_peers_ok.observe(peer_count)

    def record_get_closest_peers_error(self, error):
        self.query_result_get_closest_peers_error.labels(error=error).inc()

    # -----------------------------------------------------

    def record_get_providers_ok(self, provider_count):
        self.query_result_get_providers_ok.observe(provider_count)

    def record_get_providers_error(self, error):
        self.query_result_get_providers_error.labels(error=error).inc()

    # -----------------------------------------------------

    def record_routing_update(self, action, bucket):
        self.routing_updated.labels(
            action=action,
            bucket=str(bucket),
        ).inc()

    # -----------------------------------------------------

    def record_inbound_request(self, request_type):
        self.inbound_requests.labels(request=request_type).inc()
