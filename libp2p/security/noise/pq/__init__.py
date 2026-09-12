"""Post-quantum Noise security for py-libp2p.

Public API::

    from libp2p.security.noise.pq import TransportPQ, PROTOCOL_ID

    # Default (pure-Python kyber-py backend):
    security_options = {PROTOCOL_ID: TransportPQ(libp2p_keypair, noise_privkey)}

    # Fast ML-KEM-768 backend:
    from libp2p.security.noise.pq import make_fast_kem, KeypairPool

    kem = make_fast_kem()                           # returns MLKEM768Kem (pure Python via kyber-py)
    pool = await KeypairPool.create(kem, min_size=3) # pre-compute keypairs
"""

__all__ = [
    "PROTOCOL_ID",
    "TransportPQ",
    "KeypairPool",
    "LibOQSXWingKem",
    "make_fast_kem",
]


def __getattr__(name: str) -> object:
    if name in ("PROTOCOL_ID", "TransportPQ"):
        from .transport_pq import PROTOCOL_ID, TransportPQ

        globals()["PROTOCOL_ID"] = PROTOCOL_ID
        globals()["TransportPQ"] = TransportPQ
        return globals()[name]
    if name in ("KeypairPool", "LibOQSXWingKem", "make_fast_kem"):
        from .kem_backends import KeypairPool, LibOQSXWingKem, make_fast_kem

        globals()["KeypairPool"] = KeypairPool
        globals()["LibOQSXWingKem"] = LibOQSXWingKem
        globals()["make_fast_kem"] = make_fast_kem
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
