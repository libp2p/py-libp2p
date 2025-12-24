"""
NAT Traversal Examples for py-libp2p

This package contains examples demonstrating NAT traversal using:
- Circuit Relay v2: Relay connections through publicly reachable nodes
- DCUtR: Direct Connection Upgrade through Relay (hole punching)
- AutoNAT: Automatic NAT detection and reachability assessment

Examples:
- relay.py: Publicly reachable relay node
- listener.py: NAT'd node that advertises via relay
- dialer.py: NAT'd node that connects via relay and attempts hole punching
"""
