from prometheus_client import Counter

from libp2p.kad_dht.kad_dht import KadDhtEvent

# COUNTER

# INBOUND_REQ
# FIND_NODE
# GET_VALUE
# PUT_VALUE
# GET_PROVIDERS
# ADD_PROVIDERS


class KadDhtMetrics:
    inbound: Counter
    find_node: Counter
    get_value: Counter
    put_value: Counter
    get_providers: Counter
    add_provider: Counter

    def __init__(self):
        self.inbound = Counter(
            "kad_inbound_total",
            "Total inbound requests received",
            labelnames=["peer_id"],
        )

        self.find_node = Counter(
            "kad_inbound_find_node",
            "Total inbound FIND_NODE requests received",
            labelnames=["peer_id"],
        )

        self.get_value = Counter(
            "kad_inbound_get_value",
            "Total inbound GET_VALUE requests received",
            labelnames=["peer_id"],
        )

        self.put_value = Counter(
            "kad_inbound_put_value",
            "Total inbound PUT_VALUE requests received",
            labelnames=["peer_id"],
        )

        self.get_providers = Counter(
            "kad_inbound_get_providers",
            "Total inbound GET_PROVIDERS requests received",
            labelnames=["peer_id"],
        )

        self.add_provider = Counter(
            "kad_inbound_add_provider",
            "Total inbound ADD_PROVIDER requests received",
            labelnames=["peer_id"],
        )

    def record(self, event: KadDhtEvent) -> None:
        if event.inbound:
            self.inbound.labels(peer_id=event.peer_id).inc()

        if event.find_node:
            self.find_node.labels(peer_id=event.peer_id).inc()

        if event.get_value:
            self.get_value.labels(peer_id=event.peer_id).inc()

        if event.put_value:
            self.put_value.labels(peer_id=event.peer_id).inc()

        if event.get_providers:
            self.get_providers.labels(peer_id=event.peer_id).inc()

        if event.add_provider:
            self.add_provider.labels(peer_id=event.peer_id).inc()
