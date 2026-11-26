from prometheus_client import Counter, Histogram

from libp2p.bitswap.events import BitswapEvent


class BitswapMetrics:
    """Prometheus metrics for the Bitswap module (bounded labels only)."""

    wantlist_adds: Counter
    wantlist_cancels: Counter
    blocks_received: Counter
    blocks_sent: Counter
    block_received_bytes: Histogram
    block_sent_bytes: Histogram
    message_sent: Counter
    message_received: Counter
    message_received_bytes: Histogram
    sessions: Counter
    provider_queries: Counter
    provider_queries_found: Histogram

    def __init__(self) -> None:
        self.wantlist_adds = Counter(
            "bitswap_wantlist_adds_total",
            "Total wantlist entries added",
        )
        self.wantlist_cancels = Counter(
            "bitswap_wantlist_cancels_total",
            "Total wantlist entries cancelled",
        )
        self.blocks_received = Counter(
            "bitswap_blocks_received_total",
            "Total blocks received",
        )
        self.blocks_sent = Counter(
            "bitswap_blocks_sent_total",
            "Total blocks sent",
        )
        self.block_received_bytes = Histogram(
            "bitswap_block_received_bytes",
            "Size in bytes of received blocks",
            buckets=[64, 256, 1024, 4096, 16_384, 65_536, 262_144, 1_048_576],
        )
        self.block_sent_bytes = Histogram(
            "bitswap_block_sent_bytes",
            "Size in bytes of sent blocks",
            buckets=[64, 256, 1024, 4096, 16_384, 65_536, 262_144, 1_048_576],
        )
        self.message_sent = Counter(
            "bitswap_message_sent_total",
            "Total Bitswap messages sent",
            labelnames=["kind"],
        )
        self.message_received = Counter(
            "bitswap_message_received_total",
            "Total Bitswap messages received",
            labelnames=["kind"],
        )
        self.message_received_bytes = Histogram(
            "bitswap_message_received_bytes",
            "Size in bytes of received Bitswap messages",
            buckets=[64, 256, 1024, 4096, 16_384, 65_536, 262_144, 1_048_576],
        )
        self.sessions = Counter(
            "bitswap_sessions_total",
            "Total Bitswap sessions created",
        )
        self.provider_queries = Counter(
            "bitswap_provider_queries_total",
            "Total Bitswap DHT provider queries (one per CID)",
            labelnames=["result"],
        )
        self.provider_queries_found = Histogram(
            "bitswap_provider_queries_found",
            "Providers found per Bitswap provider query",
            buckets=[1, 2, 5, 10, 20, 50],
        )

    def record(self, event: BitswapEvent) -> None:
        # Independent ifs (not if/elif): an event may set several flags at
        # once; elif would silently drop all but the first.
        if event.want_add:
            self.wantlist_adds.inc()
        if event.want_cancel:
            self.wantlist_cancels.inc()
        if event.block_received:
            self.blocks_received.inc()
            if event.size_bytes is not None:
                self.block_received_bytes.observe(event.size_bytes)
        if event.block_sent:
            self.blocks_sent.inc()
            if event.size_bytes is not None:
                self.block_sent_bytes.observe(event.size_bytes)
        if event.message_sent:
            self.message_sent.labels(kind=event.kind or "unknown").inc()
        if event.message_received:
            self.message_received.labels(kind=event.kind or "unknown").inc()
            if event.msg_bytes is not None:
                self.message_received_bytes.observe(event.msg_bytes)
        if event.session_new:
            self.sessions.inc()
        if event.provider_query:
            result = "success" if event.success else "failure"
            self.provider_queries.labels(result=result).inc()
            if event.peers_found is not None:
                self.provider_queries_found.observe(event.peers_found)
