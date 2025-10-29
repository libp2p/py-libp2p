## Network Attack Mitigation Strategies for py-libp2p

This document outlines mitigation strategies and expected system behavior under key adversarial scenarios implemented in the `attack_simulation` test suite. It is designed to guide contributors and researchers working on hardening py-libp2p against network-level threats inspired by Polkadot/Smoldot security principles.

---

### 1. Eclipse + Bootnode Poisoning Attack

**Path:** `tests/security/attack_simulation/eclipse_attack/bootnode_poisoning.py`

#### Threat Vector

Malicious bootnodes isolate honest peers during network bootstrap. Since initial peer discovery depends on these nodes, an attacker can cut honest peers off from the canonical network.

#### Expected System Response

* Detect isolation and reduced peer diversity
* Attempt re-seeding via fallback peers
* Drop malicious connections upon detection

#### Mitigation Procedures

* Maintain bootnode diversity (geo + operator)
* Periodic bootnode rotation
* Use authenticated bootnode lists with trust anchors
* Implement fallback peer list and randomized re-seeding

---

### 2. Long-Range Fork Replay

**Path:** `tests/security/attack_simulation/fork_attack/long_range_fork.py`

#### Threat Vector

Offline nodes reconnect after long downtime and are fed an outdated fork by malicious peers. If checkpoint freshness is not validated, the node may accept stale chain data.

#### Expected System Response

* Detect stale forks through checkpoint or finality comparison
* Trigger resync with canonical chain
* Flag and isolate malicious peers

#### Mitigation Procedures

* Enforce checkpoint freshness validation
* Require multi-peer consensus on finalized state
* Use trusted checkpoint feeds for light nodes
* Maintain fallback sync sources

---

### 3. Invalid Block Propagation

**Path:** `tests/security/attack_simulation/data_attack/invalid_block.py`

#### Threat Vector

Malicious validators produce authentic but invalid blocks that light clients accept pre-finality, causing temporary inconsistencies.

#### Expected System Response

* Light clients detect invalidity post-finality
* Trigger rollback and peer isolation
* Full nodes detect earlier via state checks

#### Mitigation Procedures

* Dual validation: authenticity + integrity
* Lightweight pre-finality validity heuristics
* Rapid disconnection from malicious peers
* Alerting and telemetry hooks

---

### 4. Finality Stall Attack

**Path:** `tests/security/attack_simulation/finality_attack/stall_simulation.py`

#### Threat Vector

Finality halts while blocks continue to be produced. Light clients accumulate non-finalized blocks, potentially exhausting memory and degrading performance.

#### Expected System Response

* Detect stalled finality gossip
* Trigger timeout-based pruning of non-finalized blocks
* Throttle block processing under stall

#### Mitigation Procedures

* Prune memory aggressively during stall
* Set finality stall detection thresholds
* Resume sync and clean-up after finality resumes
* Monitor memory telemetry and trigger alerts

---

### 5. Cross-Attack Mitigation Principles

* **Bootnode Diversity:** Use multiple independent operators to prevent total isolation
* **Checkpoint Freshness:** Ensure light clients verify the recency of state checkpoints
* **Peer Behavior Monitoring:** Real-time detection of anomalous propagation
* **Fallback Paths:** Redundant peer and checkpoint sources for recovery
* **Telemetry & Alerting:** Early warning for cascading network failures

---

###  6. Testing & Benchmarking

| Attack Type        | Key Metrics                                      | Test Path                              |
| ------------------ | ------------------------------------------------ | -------------------------------------- |
| Eclipse / Bootnode | Isolation rate, DHT persistence, recovery time   | `eclipse_attack/bootnode_poisoning.py` |
| Long-Range Fork    | Fork detection rate, false acceptance rate       | `fork_attack/long_range_fork.py`       |
| Invalid Block      | Invalid block acceptance pre-finality, latency   | `data_attack/invalid_block.py`         |
| Finality Stall     | Memory growth, stall detection, recovery latency | `finality_attack/stall_simulation.py`  |

---

### Acknowledgments

These scenarios are inspired by security research in the Polkadot/Smoldot ecosystem and are extended to enhance py-libp2p’s resilience testing framework.