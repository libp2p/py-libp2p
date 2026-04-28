"""Post-quantum Noise security for py-libp2p.

Public API::

    from libp2p.security.noise.pq import TransportPQ, PROTOCOL_ID

    # Default (pure-Python kyber-py backend):
    security_options = {PROTOCOL_ID: TransportPQ(libp2p_keypair, noise_privkey)}

    # Fast backends (when liboqs C library is installed):
    from libp2p.security.noise.pq import make_fast_kem, KeypairPool

    kem = make_fast_kem()                           # auto-selects liboqs or kyber-py
    pool = await KeypairPool.create(kem, min_size=3) # pre-compute keypairs
"""

from .transport_pq import PROTOCOL_ID, TransportPQ
from .kem_backends import KeypairPool, LibOQSXWingKem, make_fast_kem

__all__ = [
    "PROTOCOL_ID",
    "TransportPQ",
    "KeypairPool",
    "LibOQSXWingKem",
    "make_fast_kem",
]
