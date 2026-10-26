import random
from typing import Any

import trio

from ..utils.attack_metrics import AttackMetrics


class GossipDelayAttacker:
    def __init__(
        self,
        topics: list[str],
        delayed_topics: list[str],
        max_delay_ms: float,
        intensity: float = 1.0,
    ):
        self.topics = topics
        self.delayed_topics = set(delayed_topics)
        self.max_delay_ms = max_delay_ms
        self.intensity = intensity
        self.messages: list[dict[str, Any]] = []

    async def generate_messages(self, count: int) -> list[dict[str, Any]]:
        self.messages = []
        for _ in range(count):
            topic = random.choice(self.topics)
            base_latency = random.uniform(20.0, 120.0)

            delay_ms = 0.0
            if topic in self.delayed_topics:
                delay_ms = random.uniform(0.0, self.max_delay_ms) * self.intensity

            total_latency = base_latency + delay_ms

            msg = {
                "topic": topic,
                "base_latency_ms": base_latency,
                "delay_ms": delay_ms,
                "total_latency_ms": total_latency,
                "delayed": delay_ms > 0.0,
            }
            self.messages.append(msg)

            await trio.sleep(0.001)

        return self.messages


class GossipDelayScenario:
    def __init__(self, attacker: GossipDelayAttacker):
        self.attacker = attacker
        self.metrics = AttackMetrics()

    async def run(self, count: int = 50) -> dict[str, Any]:
        messages = await self.attacker.generate_messages(count)

        if not messages:
            delayed_ratio = 0.0
            max_spike = 0.0
        else:
            delayed_messages = [m for m in messages if m["delayed"]]
            delayed_ratio = len(delayed_messages) / len(messages)
            max_spike = max(m["delay_ms"] for m in messages)

        # ----------------------------
        # Populate metrics
        # ----------------------------

        lookup_success_degradation = delayed_ratio
        routing_incorrect_rate = delayed_ratio * 0.2
        lookup_failure_rate = min(delayed_ratio * 0.5, 0.95)

        self.metrics.lookup_success_rate = [
            0.99,
            max(0.99 - lookup_success_degradation * 0.8, 0.3),
            0.97,
        ]
        self.metrics.lookup_failure_rate = lookup_failure_rate
        self.metrics.routing_incorrect_rate = routing_incorrect_rate

        self.metrics.avg_lookup_latency = [
            0.04,
            0.04 + delayed_ratio * 0.7,
            0.06,
        ]

        self.metrics.network_connectivity = [
            1.0,
            max(1.0 - delayed_ratio * 0.5, 0.3),
            0.9,
        ]

        self.metrics.peer_table_contamination = [
            0.0,
            min(delayed_ratio * 0.4, 1.0),
            min(delayed_ratio * 0.3, 1.0),
        ]

        self.metrics.memory_usage = [90, 90 + delayed_ratio * 15, 95]
        self.metrics.bandwidth_consumption = [30, 30 + delayed_ratio * 10, 40]
        self.metrics.cpu_utilization = [6, 6 + delayed_ratio * 12, 9]

        resilience_score = max(0.0, 1.0 - delayed_ratio * 1.5)
        self.metrics.resilience_score = resilience_score

        attack_metrics: dict[str, Any] = {
            "delayed_ratio": delayed_ratio,
            "max_latency_spike_ms": max_spike,
            "lookup_success_degradation": lookup_success_degradation,
            "routing_incorrect_rate": routing_incorrect_rate,
            "lookup_failure_rate": lookup_failure_rate,
            "avg_lookup_latency": self.metrics.avg_lookup_latency,
            "resilience_score": resilience_score,
            "network_connectivity": self.metrics.network_connectivity,
            "peer_table_contamination": self.metrics.peer_table_contamination,
        }

        return {
            "messages": messages,
            "attack_metrics": attack_metrics,
        }
