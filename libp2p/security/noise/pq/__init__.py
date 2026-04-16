"""Post-quantum Noise security for py-libp2p.

Public API::

    from libp2p.security.noise.pq import TransportPQ, PROTOCOL_ID

    security_options = {PROTOCOL_ID: TransportPQ(libp2p_keypair, noise_privkey)}
"""

from .transport_pq import PROTOCOL_ID, TransportPQ

__all__ = ["PROTOCOL_ID", "TransportPQ"]
