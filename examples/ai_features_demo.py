#!/usr/bin/env python3
"""
Demonstration script for AI-enhanced features in py-libp2p.

This script showcases:
1. Peer reputation scoring in Kademlia
2. Adaptive GossipSub tuning
3. Predictive relay decisions
4. Predictive AutoNAT
5. Anomaly detection

Run with: python examples/ai_features_demo.py
"""

import asyncio
import logging
import time
from typing import Any

import trio

from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.host.autonat import AutoNATService, AutoNATStatus
from libp2p.kad_dht import PeerRouting, RoutingTable
from libp2p.kad_dht.reputation import PeerReputationTracker
from libp2p.peer.id import ID
from libp2p.pubsub import Pubsub
from libp2p.pubsub.gossipsub import GossipSub, AdaptiveTuningConfig
from libp2p.relay.circuit_v2 import ReachabilityChecker
from libp2p.tools.anomaly_detector import AnomalyConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_features_demo")


async def demo_reputation_scoring() -> None:
    """Demonstrate peer reputation scoring in Kademlia."""
    logger.info("=" * 60)
    logger.info("Demo 1: Peer Reputation Scoring")
    logger.info("=" * 60)

    host = new_host()
    routing_table = RoutingTable(host.get_id())

    # Create a reputation tracker with custom settings
    tracker = PeerReputationTracker(
        base_score=0.5,
        success_weight=0.75,
        failure_weight=1.0,
        recency_halflife=300.0,
    )

    peer_routing = PeerRouting(host, routing_table, reputation_tracker=tracker)

    # Simulate some peer interactions
    peer1 = ID(b"peer1" * 8)
    peer2 = ID(b"peer2" * 8)
    peer3 = ID(b"peer3" * 8)

    logger.info("Recording peer interactions...")
    tracker.record_success(peer1, weight=5.0)
    tracker.record_success(peer2, weight=3.0)
    tracker.record_failure(peer3, weight=2.0)

    # Check scores
    logger.info(f"Peer 1 score: {tracker.get_score(peer1):.3f}")
    logger.info(f"Peer 2 score: {tracker.get_score(peer2):.3f}")
    logger.info(f"Peer 3 score: {tracker.get_score(peer3):.3f}")

    # Rank peers
    peers = [peer1, peer2, peer3]
    ranked = tracker.rank_peers(peers)
    logger.info(f"Ranked peers (best first): {[str(p)[:8] for p in ranked]}")

    logger.info("✓ Reputation scoring demo complete\n")


async def demo_adaptive_tuning() -> None:
    """Demonstrate adaptive GossipSub tuning."""
    logger.info("=" * 60)
    logger.info("Demo 2: Adaptive GossipSub Tuning")
    logger.info("=" * 60)

    host = new_host()
    router = GossipSub(
        protocols=[TProtocol("/meshsub/1.0.0")],
        degree=6,
        degree_low=4,
        degree_high=12,
        adaptive_tuning=True,
        adaptive_config=AdaptiveTuningConfig(
            window_size=6,
            min_degree=3,
            max_degree=32,
        ),
    )

    logger.info(f"Initial degree: {router.degree}")
    logger.info(f"Initial degree_low: {router.degree_low}")
    logger.info(f"Initial degree_high: {router.degree_high}")
    logger.info(f"Initial heartbeat_interval: {router.heartbeat_interval}")

    # Simulate some heartbeat metrics
    if router.adaptive_tuner:
        logger.info("Simulating heartbeat metrics...")
        for i in range(3):
            router.adaptive_tuner.record_heartbeat(
                mesh_sizes={"topic1": 3 + i, "topic2": 2 + i},
                fanout_sizes={"topic3": 1},
                graft_total=2,
                prune_total=1,
                gossip_total=50 + i * 10,
            )
            await trio.sleep(0.1)

        logger.info(f"After tuning - degree: {router.degree}")
        logger.info(f"After tuning - degree_low: {router.degree_low}")
        logger.info(f"After tuning - degree_high: {router.degree_high}")
        logger.info(f"After tuning - heartbeat_interval: {router.heartbeat_interval}")

    logger.info("✓ Adaptive tuning demo complete\n")


async def demo_predictive_relay() -> None:
    """Demonstrate predictive relay decisions."""
    logger.info("=" * 60)
    logger.info("Demo 3: Predictive Relay Decisions")
    logger.info("=" * 60)

    host = new_host()
    checker = ReachabilityChecker(host)

    # Create some test peer IDs
    peer1 = ID(b"test_peer_1" * 4)
    peer2 = ID(b"test_peer_2" * 4)

    logger.info("Recording connection history...")
    # Simulate some connection attempts
    checker.record_connection_result(peer1, success=True, via_relay=False, latency=0.05)
    checker.record_connection_result(peer1, success=True, via_relay=False, latency=0.06)
    checker.record_connection_result(peer2, success=False, via_relay=False, latency=None)
    checker.record_connection_result(peer2, success=False, via_relay=False, latency=None)

    # Get predictions
    decision1 = checker.predict_relay_strategy(peer1)
    decision2 = checker.predict_relay_strategy(peer2)

    logger.info(f"Peer 1 decision: {decision1.recommendation}")
    logger.info(f"Peer 1 probability: {decision1.probability:.3f}")
    logger.info(f"Peer 1 rationale: {decision1.rationale}")

    logger.info(f"Peer 2 decision: {decision2.recommendation}")
    logger.info(f"Peer 2 probability: {decision2.probability:.3f}")
    logger.info(f"Peer 2 rationale: {decision2.rationale}")

    logger.info("✓ Predictive relay demo complete\n")


async def demo_predictive_autonat() -> None:
    """Demonstrate predictive AutoNAT."""
    logger.info("=" * 60)
    logger.info("Demo 4: Predictive AutoNAT")
    logger.info("=" * 60)

    host = new_host()
    service = AutoNATService(host)

    # Simulate some dial attempts
    peer1 = ID(b"autonat_peer_1" * 4)
    peer2 = ID(b"autonat_peer_2" * 4)

    logger.info("Recording dial attempts...")
    service.dial_results[peer1] = True
    service.dial_results[peer2] = True

    # Update status (this uses the predictor internally)
    service.update_status()

    # Get prediction with confidence
    status, confidence = service.get_status_prediction()

    status_names = {
        AutoNATStatus.UNKNOWN: "UNKNOWN",
        AutoNATStatus.PUBLIC: "PUBLIC",
        AutoNATStatus.PRIVATE: "PRIVATE",
    }

    logger.info(f"Status: {status_names.get(status, 'UNKNOWN')}")
    logger.info(f"Confidence: {confidence:.3f}")
    logger.info(f"Current status: {status_names.get(service.get_status(), 'UNKNOWN')}")

    logger.info("✓ Predictive AutoNAT demo complete\n")


async def demo_anomaly_detection() -> None:
    """Demonstrate anomaly detection."""
    logger.info("=" * 60)
    logger.info("Demo 5: Anomaly Detection")
    logger.info("=" * 60)

    from libp2p.tools.anomaly_detector import PeerAnomalyDetector

    config = AnomalyConfig(
        window_seconds=60,
        publish_threshold=100,
        control_threshold=50,
        z_score_threshold=3.0,
    )

    detector = PeerAnomalyDetector(config)
    peer_id = ID(b"anomaly_test_peer" * 3)

    logger.info("Simulating normal traffic...")
    for i in range(10):
        report = detector.record(peer_id, "publish_msgs", 5.0)
        if report:
            logger.warning(f"Anomaly detected: {report}")
        await trio.sleep(0.1)

    logger.info("Simulating spike (anomaly)...")
    for i in range(20):
        report = detector.record(peer_id, "publish_msgs", 10.0)
        if report:
            logger.warning(f"Anomaly detected: {report}")
            logger.warning(f"  Metric: {report.metric}")
            logger.warning(f"  Current rate: {report.current_rate:.2f}")
            logger.warning(f"  Threshold: {report.threshold:.2f}")
            logger.warning(f"  Z-score: {report.z_score:.2f}")
            break
        await trio.sleep(0.05)

    logger.info("✓ Anomaly detection demo complete\n")


async def main() -> None:
    """Run all demos."""
    logger.info("\n" + "=" * 60)
    logger.info("py-libp2p AI Features Demonstration")
    logger.info("=" * 60 + "\n")

    try:
        await demo_reputation_scoring()
        await demo_adaptive_tuning()
        await demo_predictive_relay()
        await demo_predictive_autonat()
        await demo_anomaly_detection()

        logger.info("=" * 60)
        logger.info("All demos completed successfully!")
        logger.info("=" * 60)
        logger.info("\nFor more information, see docs/ai_features.rst")

    except Exception as e:
        logger.error(f"Demo failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    trio.run(main)

