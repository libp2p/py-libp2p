# **Network Attack Mitigation Strategies for py-libp2p**

This document outlines the mitigation strategies and expected system behavior for all adversarial scenarios implemented in the `attack_simulation` suite.

The goal is to help contributors strengthen py-libp2p’s robustness against real network adversaries by providing a clear understanding of how each attack works and how it should ideally defend itself.

______________________________________________________________________

# **📊 Attack Coverage Table**

| **Attack Type**                   | **Key Metrics Evaluated**                                                               | **Simulation Path**                     |
| --------------------------------- | --------------------------------------------------------------------------------------- | --------------------------------------- |
| **Eclipse / Bootnode Poisoning**  | Isolation rate, DHT contamination, fallback recovery time, peer diversity degradation   | `eclipse_attack/bootnode_poisoning.py`  |
| **Sybil Attack**                  | Identity amplification, fake peer influence, routing pollution, connection hijacking    | `sybil_attack/*.py`                     |
| **Flooding Attack**               | Message rate spikes, pubsub congestion, bandwidth saturation, latency inflation         | `flooding_attack/*.py`                  |
| **Invalid Block Propagation**     | Pre-finality acceptance rate, post-finality detection latency, malicious peer isolation | `data_attack/invalid_block.py`          |
| **Long-Range Fork Replay**        | Fork detection rate, false acceptance probability, resync success time                  | `fork_attack/long_range_fork.py`        |
| **Finality Stall Attack**         | Memory growth, stall detection delay, pruning performance, recovery behavior            | `finality_attack/stall_simulation.py`   |
| **Replay Attack**                 | Replayed message detection, nonce mismatch rate, out-of-order detection                 | `replay_attack/*.py`                    |
| **Routing Poisoning**             | Fake routing entries injected, lookup failure rate, routing inaccuracy                  | `routing_poisoning/*.py`                |
| **Connection Exhaustion (DoS)**   | Connection saturation, handshake exhaustion, resource starvation metrics                | `connection_exhaustion/*.py`            |
| **Protocol Violation Attack**     | Malformed message rejection, handshake exploit detection, protocol error rates          | `protocol_attack/*.py`                  |
| **Topology Partition Attack**     | Graph connectivity loss, partition size, affected nodes %, edge cut ratio               | `topology_attack/partition_attack.py`   |
| **Gossip Delay (Latency Attack)** | Latency ratio, delayed propagation %, spike size, resilience degradation                | `latency_attack/gossip_delay_attack.py` |
| **Time Drift Attack**             | Clock skew, timeout misfires, ordering instability, resilience score                    | `time_attack/time_drift_attack.py`      |
| **Simple Attack Runner**          | High-level smoke test behavior                                                          | `test_attacks_simple.py`                |
| **Unified Attack Runner**         | Multi-attack resilience verification                                                    | `test_runner.py`                        |

______________________________________________________________________

# **1. Eclipse Attack: Bootnode Poisoning**

**Path:** `eclipse_attack/bootnode_poisoning.py`

### **Threat Vector**

Malicious bootnodes mislead peers during initial discovery, creating isolated mini-networks or fully eclipsed nodes.

### **Expected System Response**

- Detect bootnode monotony (all peers coming from same source)
- Trigger fallback peer discovery
- Flag inconsistent routing table patterns

### **Mitigations**

- Maintain **bootnode diversity** (different operators, regions)
- Rotate bootnodes periodically
- Validate bootnode authenticity through signed lists
- Use peer scoring to penalize repeatedly misleading peers

______________________________________________________________________

# **2. Sybil Attack**

**Path:** `sybil_attack/*.py`

### **Threat Vector**

An attacker floods the network with fake identities to control routing or influence decisions.

### **Expected System Response**

- Detect disproportionate identity clusters
- Use scoring to reduce influence of suspicious identities
- Maintain peer diversity during selection

### **Mitigations**

- Identity cost (proof-of-work or stake, depending on chain)
- Strong peer scoring
- Reject excessive connections from same IP/subnet
- Encourage diverse routing table population

______________________________________________________________________

# **3. Flooding Attack**

**Path:** `flooding_attack/*.py`

### **Threat Vector**

Attacker sends high-volume pubsub messages, connection flood attempts, or gossip spam.

### **Expected System Response**

- Detect throughput anomalies
- Apply rate-limiting
- Evict abusive peers

### **Mitigations**

- Pubsub message rate caps
- Connection throttling
- Bandwidth quotas
- Early drop of repeated or malformed messages

______________________________________________________________________

# **4. Invalid Block Propagation**

**Path:** `data_attack/invalid_block.py`

### **Threat Vector**

Malicious validators propagate authentic-looking but invalid blocks, targeting light clients.

### **Expected System Response**

- Detect invalidity after finality
- Rollback and isolate emitter
- Prefer multiple validation sources

### **Mitigations**

- Dual-validity checks: authenticity + state integrity
- Cache recent finality checkpoints
- Require multi-peer agreement before pre-finality acceptance
- Rapid blacklist of invalid block producers

______________________________________________________________________

# **5. Long-Range Fork Replay**

**Path:** `fork_attack/long_range_fork.py`

### **Threat Vector**

Nodes offline for long durations may be fed outdated chain histories by malicious peers.

### **Expected System Response**

- Compare against trusted checkpoints
- Detect outdated finality
- Re-sync to canonical chain

### **Mitigations**

- Enforce checkpoint freshness validation
- Multi-peer consensus for finalized state
- Maintain trusted, rotating checkpoint providers
- Reject unanchored long-range histories

______________________________________________________________________

# **6. Finality Stall Attack**

**Path:** `finality_attack/stall_simulation.py`

### **Threat Vector**

Finality stops while block production continues, causing memory bloat and inconsistent state in light clients.

### **Expected System Response**

- Detect stalled finality streams
- Trigger pruning of non-finalized blocks
- Pause aggressive block acceptance

### **Mitigations**

- Memory-pruning limits
- Finality stall detection thresholds
- Auto-throttle block intake
- Resume sync and garbage-collect old blocks after recovery

______________________________________________________________________

# **7. Replay Attack**

**Path:** `replay_attack/*.py`

### **Threat Vector**

Attacker captures valid messages and replays them to confuse peers or manipulate state transitions.

### **Expected System Response**

- Track nonces / timestamps
- Reject duplicates
- Detect out-of-order sequences

### **Mitigations**

- Nonce-based replay protection
- Soft time-window validation
- Detection of repetitive patterns
- Peer scoring penalties

______________________________________________________________________

# **8. Routing Poisoning Attack**

**Path:** `routing_poisoning/*.py`

### **Threat Vector**

Malicious peers inject fake routing entries to pollute DHT results.

### **Expected System Response**

- Detect inconsistent routing entries
- Reduce trust in suspicious sources
- Cross-check entries across peers

### **Mitigations**

- Multi-peer confirmation before accepting routing entries
- Penalize peers advertising excessive fake entries
- Maintain routing table diversity
- Perform periodic route cleanup

______________________________________________________________________

# **9. Connection Exhaustion (DoS)**

**Path:** `connection_exhaustion/*.py`

### **Threat Vector**

Attacker opens many simultaneous connections to exhaust file descriptors and memory.

### **Expected System Response**

- Connection caps engage
- Reject new connections gracefully
- Evict least-scored peers

### **Mitigations**

- Per-peer connection limits
- Global connection limits
- Adaptive backoff
- Resource-aware connection prioritization

______________________________________________________________________

# **10. Protocol Violation Attack**

**Path:** `protocol_attack/*.py`

### **Threat Vector**

Malformed messages, handshake exploits, invalid protocol steps, or inconsistent payloads.

### **Expected System Response**

- Reject malformed payloads
- Trigger protocol error events
- Isolate recurring offenders

### **Mitigations**

- Strict schema validation
- Enforce handshake invariants
- Runtime protocol sanity checks
- Peer scoring for violations

______________________________________________________________________

# **11. Topology Partition Attack**

**Path:** `topology_attack/partition_attack.py`

### **Threat Vector**

Adversary partitions the network into disconnected components, breaking routing and consensus.

### **Expected System Response**

- Detect graph connectivity drop
- Attempt alternate edges
- Trigger recovery via fallback peers

### **Mitigations**

- Encourage mesh diversity
- Maintain redundant paths
- Topology monitoring
- Periodic reconnection to random nodes

______________________________________________________________________

# **12. Gossip Delay (Latency Attack)**

**Path:** `latency_attack/gossip_delay_attack.py`

### **Threat Vector**

Attacker introduces targeted latency to delay gossip propagation, affecting block production, routing and consensus liveness.

### **Expected System Response**

- Detect latency spikes
- Identify chronically slow peers
- Adapt gossip heartbeat speeds

### **Mitigations**

- Latency scoring
- Slow-peer eviction
- Prioritize fast-forward peers
- Enforce max gossip delay thresholds

______________________________________________________________________

# **13. Time Drift Attack**

**Path:** `time_attack/time_drift_attack.py`

### **Threat Vector**

Nodes experience clock drift (positive or negative), causing timeout misfires, ordering errors and inconsistent state views.

### **Expected System Response**

- Detect drift using heartbeat timestamps
- Adjust timeout thresholds
- Account for max drift in ordering logic

### **Mitigations**

- Clock synchronization heuristics
- Drift-tolerant timeout windows
- Sequence numbers for ordering
- Penalize peers with extreme drift

______________________________________________________________________

# **Cross-Attack Mitigation Principles**

Across all attacks, the following principles improve resilience:

- **Peer diversity:** avoid relying on single sources of truth
- **Fallback paths:** provide alternate discovery and validation mechanisms
- **Peer scoring:** down-rank malicious or unstable peers
- **Telemetry & alerts:** early detection of anomalies
- **Adaptive algorithms:** network-aware timeouts and thresholds
- **Redundant validation:** multi-peer confirmations for critical data
