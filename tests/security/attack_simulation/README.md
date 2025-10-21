# Network Attack Simulation Framework for py-libp2p

A comprehensive network attack simulation framework for testing P2P network security in py-libp2p.

[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](https://github.com/libp2p/py-libp2p)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT%20%2F%20Apache--2.0-blue.svg)](https://github.com/libp2p/py-libp2p)

## Features

- Simulates Eclipse, Sybil, Flooding, Connection Exhaustion and Protocol attacks
- Real-time metrics and comprehensive analytics
- Dual-layer architecture with simulation and real network testing
- Extensive test coverage and configuration options

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
├── eclipse_attack/     # Eclipse attack simulation
├── sybil_attack/      # Sybil attack simulation
├── flooding_attack/   # Flooding attack simulation
├── connection_exhaustion/ # Connection exhaustion
├── protocol_attack/   # Protocol attack simulation
├── replay_attack/     # Replay attack simulation
├── routing_poisoning/ # Routing Poisoning attack simulation
├── utils/            # Shared utilities
├── config/           # Configurations
└── results/          # Test results
```

## License

Dual licensed under MIT and Apache 2.0.

See [LICENSE-MIT](../../../LICENSE-MIT) and [LICENSE-APACHE](../../../LICENSE-APACHE).

*Built with ❤️ for P2P network security research*
