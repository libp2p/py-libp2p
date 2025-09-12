# Hole Punching Implementation for py-libp2p

## What This Adds

This implementation adds hole punching capability to py-libp2p, allowing peers behind NATs to connect directly.

## Components

- **DCUtR Protocol**: Coordinates hole punching between peers
- **AutoNAT Service**: Detects if peer is behind NAT (basic implementation)
- **Examples**: Working code showing how to use hole punching

## Quick Start

1. Install py-libp2p with hole punching:
```bash
pip install -e .[dev]
```
2. Run basic example:
```bash
# Terminal 1
python examples/hole_punching/basic_example.py --mode listen

# Terminal 2 (use peer ID from terminal 1)  
python examples/hole_punching/basic_example.py --mode dial --target PEER_ID
```

## Current Status
-Basic DCUtR protocol implementation
- Working example code
- Basic tests

## Testing
```bash
pytest tests/interop/ -v
```
