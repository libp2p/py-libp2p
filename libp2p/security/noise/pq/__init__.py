"""Post-quantum Noise security for py-libp2p.

Public API::

    from libp2p.security.noise.pq import TransportPQ, PROTOCOL_ID

    # Default (pure-Python kyber-py backend):
    security_options = {PROTOCOL_ID: TransportPQ(libp2p_keypair, noise_privkey)}

    # The KEM directly, or a pre-computed keypair pool:
    from libp2p.security.noise.pq import MLKEM768Kem, KeypairPool

    kem = MLKEM768Kem()                              # pure Python, via kyber-py
    pool = await KeypairPool.create(kem, min_size=3) # pre-compute keypairs
"""

__all__ = [
    "PROTOCOL_ID",
    "TransportPQ",
    "KeypairPool",
    "MLKEM768Kem",
    "make_fast_kem",
]


def __getattr__(name: str) -> object:
    if name in ("PROTOCOL_ID", "TransportPQ"):
        from .transport_pq import PROTOCOL_ID, TransportPQ

        globals()["PROTOCOL_ID"] = PROTOCOL_ID
        globals()["TransportPQ"] = TransportPQ
        return globals()[name]
    if name in ("KeypairPool", "make_fast_kem"):
        from .kem_backends import KeypairPool, make_fast_kem

        globals()["KeypairPool"] = KeypairPool
        globals()["make_fast_kem"] = make_fast_kem
        return globals()[name]
    if name == "MLKEM768Kem":
        from .kem import MLKEM768Kem

        globals()["MLKEM768Kem"] = MLKEM768Kem
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
