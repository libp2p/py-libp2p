AI-Enhanced Features in py-libp2p
===================================

py-libp2p now includes several AI-powered features that enhance network performance,
security, and user experience. All features are optional and can be enabled as needed.

Peer Reputation Scoring (Kademlia DHT)
---------------------------------------

The Kademlia peer routing system now includes a lightweight reputation tracker that
prioritizes reliable peers during network lookups.

**Location**: ``libp2p/kad_dht/reputation.py``

**Usage**:

.. code-block:: python

    from libp2p.kad_dht import PeerRouting, RoutingTable, PeerReputationTracker
    from libp2p import new_host

    host = new_host()
    routing_table = RoutingTable(host.get_id())
    
    # Create a custom reputation tracker (optional)
    tracker = PeerReputationTracker(
        base_score=0.5,
        success_weight=0.75,
        failure_weight=1.0,
        recency_halflife=300.0
    )
    
    # PeerRouting automatically uses reputation scoring
    peer_routing = PeerRouting(host, routing_table, reputation_tracker=tracker)
    
    # The tracker automatically records successes/failures during lookups
    # and ranks peers by reputation when selecting query targets

**How it works**:
- Tracks success/failure counts per peer
- Applies recency weighting (recent successes boost score)
- Automatically ranks peers during iterative lookups
- Extensible for future ML-based scoring models

Adaptive GossipSub Tuning
--------------------------

GossipSub router can now automatically adjust mesh parameters based on network
conditions to optimize message delivery and reduce overhead.

**Location**: ``libp2p/pubsub/adaptive_tuner.py``

**Usage**:

.. code-block:: python

    from libp2p.pubsub.gossipsub import GossipSub, AdaptiveTuningConfig
    from libp2p.custom_types import TProtocol

    # Enable adaptive tuning when creating GossipSub
    router = GossipSub(
        protocols=[TProtocol("/meshsub/1.0.0")],
        degree=6,
        degree_low=4,
        degree_high=12,
        adaptive_tuning=True,  # Enable adaptive tuning
        adaptive_config=AdaptiveTuningConfig(
            window_size=6,
            min_degree=3,
            max_degree=32,
            min_heartbeat_interval=20,
            max_heartbeat_interval=240
        )
    )

**What it adjusts**:
- **Mesh degree**: Increases/decreases based on mesh stability
- **Heartbeat interval**: Adjusts based on gossip message volume
- **PX peer count**: Optimizes peer exchange based on connectivity

**How it works**:
- Monitors heartbeat metrics (mesh sizes, graft/prune counts, gossip volume)
- Uses moving averages to detect trends
- Gradually adjusts parameters within safe bounds
- Logs all adjustments for observability

AI Chat Assistant
-----------------

The chat demo now includes an optional AI assistant that can summarize conversations
or provide automatic replies.

**Location**: ``examples/chat/assistant.py``

**Usage**:

.. code-block:: bash

    # Enable AI assistant with summary mode
    python examples/chat/chat.py --ai-assistant --ai-mode summary -p 8000
    
    # Enable AI assistant with reply mode
    python examples/chat/chat.py --ai-assistant --ai-mode reply --ai-frequency 3 -p 8000
    
    # Use a custom Hugging Face model
    python examples/chat/chat.py --ai-assistant --ai-model "gpt2" -p 8000

**Modes**:
- **summary**: Periodically prints conversation summaries
- **reply**: Automatically sends AI-generated replies

**Features**:
- Works without external dependencies (uses heuristic fallbacks)
- Optional Hugging Face integration for real LLM models
- Configurable frequency for summaries/replies
- Maintains conversation history

Predictive Relay Decisions
---------------------------

The relay system now uses predictive models to determine when peers are likely to
need relay support, avoiding unnecessary hole punching attempts.

**Location**: ``libp2p/relay/circuit_v2/predictor.py``

**Usage**:

.. code-block:: python

    from libp2p.relay.circuit_v2 import ReachabilityChecker
    from libp2p import new_host

    host = new_host()
    checker = ReachabilityChecker(host)
    
    # Check if a peer likely needs relay
    decision = checker.predict_relay_strategy(peer_id)
    
    if decision.recommendation == "prefer_relay":
        # Use relay instead of attempting direct connection
        pass
    elif decision.recommendation == "try_direct":
        # Attempt direct connection first
        pass

**Decision factors**:
- Address quality (public vs private IPs)
- Historical connection success rates
- Observed latency patterns
- Recent connection attempts

**Integration**:
- Automatically used by DCUtR protocol
- Records connection outcomes for learning
- Provides confidence scores and rationale

Predictive AutoNAT
-------------------

AutoNAT service now provides confidence-scored status predictions based on historical
dial attempt patterns.

**Location**: ``libp2p/host/autonat/predictor.py``

**Usage**:

.. code-block:: python

    from libp2p.host.autonat import AutoNATService
    from libp2p import new_host

    host = new_host()
    service = AutoNATService(host)
    
    # Get status with confidence
    status, confidence = service.get_status_prediction()
    
    if confidence > 0.8:
        print(f"High confidence: Status is {status}")
    else:
        print(f"Low confidence ({confidence:.2f}): Status is {status}")

**Features**:
- Weighted history analysis
- Confidence scoring (0.0 to 1.0)
- Automatic status updates based on dial results
- Extensible for future ML models

Anomaly Detection Framework
---------------------------

A lightweight anomaly detection system monitors peer behavior and automatically
blacklists abusive peers in pubsub networks.

**Location**: ``libp2p/tools/anomaly_detector.py``

**Usage**:

.. code-block:: python

    from libp2p.pubsub import Pubsub
    from libp2p.pubsub.gossipsub import GossipSub
    from libp2p.tools.anomaly_detector import PeerAnomalyDetector, AnomalyConfig
    from libp2p import new_host

    host = new_host()
    router = GossipSub(...)
    
    # Create pubsub with anomaly detection
    pubsub = Pubsub(
        host,
        router,
        enable_anomaly_detection=True,  # Enable detection
        anomaly_config=AnomalyConfig(
            window_seconds=60,
            publish_threshold=100,  # Messages per window
            control_threshold=50,    # Control messages per window
            z_score_threshold=3.0
        )
    )

**What it detects**:
- Message flooding (excessive publish messages)
- Control message spam (excessive graft/prune/ihave)
- Unusual traffic patterns (statistical outliers)

**Actions**:
- Automatically blacklists detected peers
- Logs detection events with details
- Provides metrics for tuning thresholds

**Configuration**:
- Adjustable time windows
- Configurable thresholds per metric
- Z-score sensitivity tuning

Best Practices
--------------

1. **Start with defaults**: All features work with default configurations
2. **Monitor logs**: AI features log their decisions for observability
3. **Tune gradually**: Adjust parameters based on your network characteristics
4. **Test in staging**: Verify behavior before deploying to production
5. **Combine features**: Features work together synergistically

Performance Considerations
--------------------------

- **Reputation tracking**: Minimal overhead, in-memory only
- **Adaptive tuning**: Runs during heartbeats, negligible impact
- **Anomaly detection**: O(1) per message, efficient sliding windows
- **Predictive models**: Lightweight heuristics, no heavy ML by default

Future Enhancements
-------------------

All AI features are designed to be extensible:

- **ML model integration**: Replace heuristics with trained models
- **Federated learning**: Share insights across nodes (privacy-preserving)
- **Advanced anomaly detection**: LSTM autoencoders for pattern detection
- **Reinforcement learning**: Optimize parameters via RL agents

Contributing
------------

We welcome contributions to improve these AI features. Areas of interest:

- Better heuristics and scoring algorithms
- Integration with external ML frameworks
- Performance optimizations
- Additional detection patterns
- Telemetry and metrics

See the main `contributing.rst` guide for details.

