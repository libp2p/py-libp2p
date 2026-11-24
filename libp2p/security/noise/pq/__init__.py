"""Post-quantum Noise security for py-libp2p.

Public API::

    from libp2p.security.noise.pq import TransportPQ, PROTOCOL_ID

    # Default backend selection is make_fast_kem(): the native ML-KEM-768
    # backend when cryptography provides it, kyber-py otherwise.
    security_options = {PROTOCOL_ID: TransportPQ(libp2p_keypair, noise_privkey)}

    # A KEM directly, or a pre-computed keypair pool:
    from libp2p.security.noise.pq import (
        MLKEM768Kem, MLKEM768NativeKem, KeypairPool,
    )

    kem = MLKEM768NativeKem()                        # native, via cryptography
    kem = MLKEM768Kem()                              # pure Python, via kyber-py
    pool = await KeypairPool.create(kem, min_size=3) # pre-compute keypairs
"""

__all__ = [
    "PROTOCOL_ID",
    "TransportPQ",
    "KeypairPool",
    "MLKEM768Kem",
    "MLKEM768NativeKem",
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
    if name in ("MLKEM768Kem", "MLKEM768NativeKem"):
        from .kem import MLKEM768Kem, MLKEM768NativeKem

        globals()["MLKEM768Kem"] = MLKEM768Kem
        globals()["MLKEM768NativeKem"] = MLKEM768NativeKem
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
