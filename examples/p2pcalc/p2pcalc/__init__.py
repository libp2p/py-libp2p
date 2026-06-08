"""
P2PCalc - Decentralised EtherCalc collaboration over py-libp2p GossipSub.

Core components:
- operation: protocol, HLC, operation encoding
- crdt: MVR and RGA CRDT implementations
- p2p_node: libp2p + GossipSub networking
- adapter: EtherCalc Redis bridge
- state_sync: snapshot and WAL recovery
"""