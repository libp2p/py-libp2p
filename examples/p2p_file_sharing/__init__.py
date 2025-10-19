"""
P2P File Sharing Application

A lightweight file-sharing application that enables peers to discover each other
via peerstore and exchange files using NAT traversal (STUN/relay if needed).

This demonstrates:
- NAT traversal using Circuit Relay v2 and DCUtR
- Peer discovery and persistence using peerstore
- Direct peer-to-peer file transfer across NATs
- Automatic fallback to relay when direct connection fails
"""

__version__ = "1.0.0"
