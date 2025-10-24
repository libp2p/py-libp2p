# Network Attack Simulation Framework for py-libp2p

A comprehensive network attack simulation framework for testing P2P network security in py-libp2p.

[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](https://github.com/libp2p/py-libp2p)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT%20%2F%20Apache--2.0-blue.svg)](https://github.com/libp2p/py-libp2p)

## Features

- **Core Attack Simulations**: Eclipse, Sybil, Flooding, Connection Exhaustion, Protocol attacks
- **Extended Threat Model** (Polkadot/Smoldot-inspired):
  - Bootnode Poisoning (network isolation)
  - Long-Range Fork Replay (temporal attacks)
  - Invalid Block Propagation (light client vulnerabilities)
  - Finality Stall Simulation (resource exhaustion)
- Real-time metrics and comprehensive analytics
- Dual-layer architecture with simulation and real network testing
- Extensive test coverage and configuration options
- Production-grade mitigation strategies documentation

## Quick Start

```bash
# Install
cd /path/to/py-libp2p
source .venv/bin/activate
pip install -e .

# Run tests
pytest tests/security/attack_simulation/ -v
```

## Structure

```
tests/security/attack_simulation/
├── eclipse_attack/        # Eclipse attack simulation
│   └── bootnode_poisoning.py  # Bootnode poisoning attack
├── sybil_attack/          # Sybil attack simulation
├── flooding_attack/       # Flooding attack simulation
├── connection_exhaustion/ # Connection exhaustion
├── protocol_attack/       # Protocol attack simulation
├── replay_attack/         # Replay attack simulation
├── routing_poisoning/     # Routing Poisoning attack simulation
├── fork_attack/           # Long-range fork replay attack
│   └── long_range_fork.py
├── data_attack/           # Invalid block propagation attack
│   └── invalid_block.py
├── finality_attack/       # Finality stall simulation
│   └── stall_simulation.py
├── utils/                 # Shared utilities
├── config/                # Configurations
├── docs/                  # Documentation
│   └── mitigations.md    # Comprehensive mitigation strategies
└── results/               # Test results
```

## Extended Threat Model

The framework includes an **extended threat model** inspired by Polkadot/Smoldot network security research:

### 1. Bootnode Poisoning Attack

Simulates complete bootnode compromise leading to network isolation.

```bash
pytest tests/security/attack_simulation/eclipse_attack/test_bootnode_poisoning.py -v
```

**Key Metrics**: Isolation rate, recovery success, fallback peer effectiveness

### 2. Long-Range Fork Replay Attack

Tests resilience against stale chain replay for nodes offline beyond validator unstaking period.

```bash
pytest tests/security/attack_simulation/fork_attack/test_long_range_fork.py -v
```

**Key Metrics**: Fork detection rate, false acceptance rate, resync success

### 3. Invalid Block Propagation Attack

Evaluates light client vulnerability to authentic-but-invalid blocks.

```bash
pytest tests/security/attack_simulation/data_attack/test_invalid_block.py -v
```

**Key Metrics**: Light client acceptance rate, post-finality detection, vulnerability gap

### 4. Finality Stall Simulation

Measures memory exhaustion when finality halts while block production continues.

```bash
pytest tests/security/attack_simulation/finality_attack/test_stall_simulation.py -v
```

**Key Metrics**: Memory exhaustion rate, timeout detection, recovery time

## Mitigation Strategies

Comprehensive mitigation documentation available at:

```
tests/security/attack_simulation/docs/mitigations.md
```

Covers:

- Defense strategies for each attack type
- Implementation priorities
- Recovery procedures
- Performance metrics
- Cross-attack defense patterns

## Configuration

Extended threat model configurations in `config/attack_configs.py`:

- `BOOTNODE_POISONING_CONFIGS`
- `LONG_RANGE_FORK_CONFIGS`
- `INVALID_BLOCK_CONFIGS`
- `FINALITY_STALL_CONFIGS`

## Running All Tests

```bash
# Run all attack simulations
pytest tests/security/attack_simulation/ -v

# Run extended threat model tests only
pytest tests/security/attack_simulation/eclipse_attack/test_bootnode_poisoning.py \
      tests/security/attack_simulation/fork_attack/ \
      tests/security/attack_simulation/data_attack/ \
      tests/security/attack_simulation/finality_attack/ -v

# Generate comprehensive report
pytest tests/security/attack_simulation/ -v --html=report.html --self-contained-html
```

## Performance Benchmarks

Target resilience metrics across all attack vectors:

- **Attack Resilience**: 95%+ defense success rate
- **Detection Latency**: < 2 minutes
- **Recovery Time**: < 5 minutes
- **False Positive Rate**: < 5%

## Research & Acknowledgments

This extended threat model is inspired by:

- Polkadot/Smoldot network security architecture
- Web3 Foundation security research
- Academic research on P2P network attacks
- Real-world attack patterns from production networks

Special thanks to contributors of PR #950 and the libp2p security working group.

## License

Dual licensed under MIT and Apache 2.0.

See [LICENSE-MIT](../../../LICENSE-MIT) and [LICENSE-APACHE](../../../LICENSE-APACHE).

*Built with ❤️ for P2P network security research*
