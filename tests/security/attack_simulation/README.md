# Network Attack Simulation Module (py-libp2p)

This module provides a **network attack simulation framework** for py-libp2p, focused on testing **P2P network security**. It is implemented as a **submodule** inside py-libp2p to simulate attacks, measure metrics, and analyze network resilience.

______________________________________________________________________

## Table of Contents

1. [Module Overview](#module-overview)
1. [Module Structure](#module-structure)
1. [Setup and Usage](#setup-and-usage)
1. [Testing](#testing)
1. [Implementation Details](#implementation-details)
1. [Metrics and Analysis](#metrics-and-analysis)
1. [Roadmap](#roadmap)
1. [Eclipse Attack Flow](#eclipse-attack-flow)
1. [Contributing](#contributing)

______________________________________________________________________

## Module Overview

This module simulates network attacks in a controlled py-libp2p environment. Current focus:

- **Eclipse attacks** by poisoning DHTs
- Metrics collection for network health and attack effectiveness
- Configurable attack scenarios and network topologies
- Foundation for future attack types (Sybil, flooding, protocol exploits)

All work is **local in py-libp2p** with a planned migration path to `libp2p/interop`.

______________________________________________________________________

## Module Structure

```
tests/security/attack_simulation/
├── eclipse_attack/
│   ├── test_eclipse_simulation.py      # Main test suite for Eclipse attacks
│   ├── malicious_peer.py               # Malicious peer behavior implementation
│   ├── metrics_collector.py            # Collects attack metrics during simulation
│   ├── attack_scenarios.py             # Defines Eclipse attack scenarios
│   ├── network_builder.py              # Builds test networks with honest/malicious nodes
│   ├── real_network_builder.py         # Real libp2p host integration
│   ├── real_metrics_collector.py       # Real network performance metrics
│   └── test_real_eclipse_simulation.py # Integration tests with actual DHTs
├── utils/
│   ├── attack_metrics.py               # Metrics calculation utilities
│   ├── peer_behavior_simulator.py      # Simulates peer behaviors (honest and malicious)
│   └── network_monitor.py              # Monitors network state and connectivity
├── config/
│   ├── attack_configs.py               # Configuration options for attacks
│   └── network_topologies.py           # Predefined network topologies
└── README.md                           # Module documentation and usage guide
```

______________________________________________________________________

## Setup and Usage

1. **Activate py-libp2p virtual environment**:

```bash
source .venv/bin/activate
```

2. **Run the simulation framework tests**:

```bash
pytest -v tests/security/attack_simulation/eclipse_attack/test_eclipse_simulation.py
```

3. **Run the REAL integration tests** (🆕 **Actual libp2p network attacks**):

```bash
pytest -v tests/security/attack_simulation/eclipse_attack/test_real_eclipse_simulation.py
```

4. **Run individual attack demo**:

```bash
python tests/security/attack_simulation/eclipse_attack/test_real_eclipse_simulation.py demo
```

> Tests validate both simulated and real network attack scenarios.

______________________________________________________________________

## Testing

The module provides **two levels** of testing:

### **Level 1: Simulation Framework** (Original Implementation)
- Eclipse attack tests (`eclipse_attack/test_eclipse_simulation.py`)
- Utilities: metrics, network monitoring, peer behavior
- **Fast execution**, **conceptual validation**

### **Level 2: Real Integration Tests** 🆕 (New Enhancement)
- Real libp2p host creation using `HostFactory`
- Actual DHT manipulation with `KadDHT` instances  
- Real network performance measurement
- **Slower execution**, **actual security testing**

Passing tests confirm:

- ✅ **Simulation Framework**: Network setup, malicious behaviors, metrics collection  
- ✅ **Real Integration**: Actual libp2p attacks, DHT poisoning, performance degradation

______________________________________________________________________

## Implementation Details

### **Simulation Layer** (Original)

#### Malicious Peer
```python
class MaliciousPeer:
    """Simulates malicious peer behavior"""
```

#### Network Builder
```python
class AttackNetworkBuilder:
    """Constructs configurable test networks for attack simulations"""
```

### **Real Integration Layer** 🆕 (New Enhancement)

#### Real Malicious Peer
```python
class RealMaliciousPeer(MaliciousPeer):
    """Real malicious peer that manipulates actual DHT instances"""
    
    async def poison_real_dht_entries(self, target_dht: KadDHT):
        # Actually poison real DHT routing tables
        
    async def flood_real_peer_table(self, target_dht: KadDHT):  
        # Flood real DHT with malicious entries
```

#### Real Network Builder
```python  
class RealNetworkBuilder(AttackNetworkBuilder):
    """Builds networks with real libp2p hosts and DHT instances"""
    
    async def create_real_eclipse_test_network(self):
        # Uses HostFactory to create actual libp2p hosts
        # Creates real KadDHT instances
        # Forms realistic network topologies
```

#### Real Metrics Collector
```python
class RealAttackMetrics(AttackMetrics):
    """Collects actual performance metrics from real libp2p networks"""
    
    async def measure_complete_attack_cycle(self):
        # Measures real DHT lookup degradation
        # Tracks actual network connectivity loss
        # Calculates genuine recovery metrics
```

______________________________________________________________________

## Metrics and Analysis

Tracked metrics:

- DHT lookup success/failure rates
- Peer table contamination
- Network connectivity
- Attack effectiveness and recovery metrics

```python
class AttackMetrics:
    """Metrics collection and analysis framework"""
```

______________________________________________________________________

## Roadmap

**Phase 1 (Current)**: Eclipse attack simulation

**Phase 2**: Extended attacks (Sybil, flooding, connection exhaustion)

**Phase 3**: Cross-implementation testing in `libp2p/interop`

______________________________________________________________________

## Eclipse Attack Flow

```mermaid
flowchart TD
    A[Network Builder] --> B[Honest Peers]
    A --> C[Malicious Peers]
    C --> D[Poison DHT Entries]
    C --> E[Flood Peer Tables]
    B --> F[Perform Lookups]
    D --> F
    E --> F
    F --> G[Metrics Collector]
    G --> H[Attack Analysis & Reporting]
```

> This flow illustrates the lifecycle of an Eclipse attack: the network is built, malicious peers poison the DHT and flood peer tables, honest peers perform lookups, and metrics are collected and analyzed.

______________________________________________________________________

## Contributing

1. Add new Eclipse attack scenarios under eclipse_attack, and shared utilities for any attack under utils.
1. Implement new metrics or monitoring tools
1. Write corresponding pytest tests
1. Submit PR to py-libp2p for review
