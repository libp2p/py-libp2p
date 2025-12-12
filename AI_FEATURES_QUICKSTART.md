# AI Features Quick Start Guide

This guide provides a quick overview of the AI-enhanced features in py-libp2p.

## Quick Links

- **Full Documentation**: See `docs/ai_features.rst`
- **Demo Script**: Run `python examples/ai_features_demo.py`
- **Chat with AI**: `python examples/chat/chat.py --ai-assistant --ai-mode summary`

## Features at a Glance

### 1. Peer Reputation Scoring (Kademlia)
**What**: Automatically prioritizes reliable peers during DHT lookups.

**Enable**: Automatic (built into `PeerRouting`)

**Customize**:
```python
from libp2p.kad_dht.reputation import PeerReputationTracker
tracker = PeerReputationTracker(base_score=0.5, success_weight=0.75)
peer_routing = PeerRouting(host, routing_table, reputation_tracker=tracker)
```

### 2. Adaptive GossipSub Tuning
**What**: Automatically adjusts mesh parameters based on network conditions.

**Enable**:
```python
router = GossipSub(..., adaptive_tuning=True)
```

**Monitor**: Check logs for "Adaptive tuning" messages.

### 3. AI Chat Assistant
**What**: Optional AI assistant for chat demos (summaries or auto-replies).

**Enable**:
```bash
python examples/chat/chat.py --ai-assistant --ai-mode summary -p 8000
```

**Modes**: `summary` (periodic summaries) or `reply` (auto-replies)

### 4. Predictive Relay Decisions
**What**: Predicts when peers need relay support, avoiding failed hole punches.

**Enable**: Automatic (built into `ReachabilityChecker`)

**Use**:
```python
checker = ReachabilityChecker(host)
decision = checker.predict_relay_strategy(peer_id)
if decision.recommendation == "prefer_relay":
    # Use relay
```

### 5. Predictive AutoNAT
**What**: Provides confidence-scored NAT status predictions.

**Enable**: Automatic (built into `AutoNATService`)

**Use**:
```python
service = AutoNATService(host)
status, confidence = service.get_status_prediction()
```

### 6. Anomaly Detection
**What**: Automatically detects and blacklists abusive peers in pubsub.

**Enable**:
```python
pubsub = Pubsub(host, router, enable_anomaly_detection=True)
```

**Configure**:
```python
from libp2p.tools.anomaly_detector import AnomalyConfig
config = AnomalyConfig(
    window_seconds=60,
    publish_threshold=100,
    control_threshold=50
)
pubsub = Pubsub(host, router, enable_anomaly_detection=True, anomaly_config=config)
```

## Testing

Run the comprehensive demo:
```bash
python examples/ai_features_demo.py
```

Test chat with AI:
```bash
# Terminal 1
python examples/chat/chat.py --ai-assistant --ai-mode summary -p 8000

# Terminal 2
python examples/chat/chat.py --ai-assistant --ai-mode summary -d /ip4/127.0.0.1/tcp/8000/p2p/<peer_id>
```

## Configuration Tips

1. **Start with defaults**: All features work out of the box
2. **Monitor logs**: AI decisions are logged for observability
3. **Tune gradually**: Adjust parameters based on your network
4. **Combine features**: Features work together synergistically

## Performance

- **Overhead**: Minimal - all features use lightweight heuristics
- **Memory**: In-memory only, no persistent storage required
- **CPU**: Negligible impact, runs during existing operations

## Extensibility

All features are designed to be extensible:
- Replace heuristics with ML models
- Add custom scoring algorithms
- Integrate external ML frameworks
- Add new detection patterns

## Support

- **Documentation**: `docs/ai_features.rst`
- **Issues**: GitHub Issues
- **Discord**: #py-libp2p channel

## Release Notes

See `newsfragments/1015.feature.rst` for detailed feature descriptions.

