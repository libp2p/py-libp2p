#!/usr/bin/env python3
"""
Generate cross-implementation test vectors for
``Noise_XXhfs_25519+MLKEM768_ChaChaPoly_SHA256`` (``/noise-mlkem768-hfs/0.2.0``).

The vectors pin the wire bytes of all three handshake messages plus the derived
handshake hash and transport keys, so that Python, Rust and JS implementations can
be checked against the same file rather than against each other by hand. This is
what libp2p/specs#723 asks for.

Method
------
Rather than reimplementing the handshake here, which could silently drift from the
implementation it is meant to pin, this drives the real ``PatternXXhfs`` over an
in-memory connection pair and records what it puts on the wire. Every source of
randomness is replaced by a deterministic one for the duration:

* ephemeral X25519 secrets come from the vector's seeds, not ``nacl.utils.random``
* ML-KEM-768 keygen uses FIPS 203 ``_keygen_internal`` via ``key_derive(d||z)``
* ML-KEM-768 encapsulation uses FIPS 203 ``_encaps_internal(ek, m)``

**The seeded keys in the output are for reproducibility only. They must never be
used for anything real.**

Usage:
    python scripts/gen_pq_test_vectors.py [-o OUTPUT.json] [-n COUNT]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

import trio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from multiaddr import Multiaddr  # noqa: E402
from nacl.bindings import crypto_scalarmult_base  # noqa: E402
import nacl.utils  # noqa: E402

from libp2p.abc import IRawConnection  # noqa: E402
from libp2p.connection_types import ConnectionType  # noqa: E402
from libp2p.crypto.ed25519 import create_new_key_pair  # noqa: E402
from libp2p.crypto.x25519 import X25519PrivateKey  # noqa: E402
from libp2p.peer.id import ID  # noqa: E402
from libp2p.security.noise.pq import noise_state  # noqa: E402
from libp2p.security.noise.pq.patterns_pq import PatternXXhfs  # noqa: E402

PROTOCOL = "Noise_XXhfs_25519+MLKEM768_ChaChaPoly_SHA256"
PROTOCOL_ID = "/noise-mlkem768-hfs/0.2.0"

MLKEM768_PK = 1184
MLKEM768_CT = 1088
X25519 = 32


class _MemoryConn(IRawConnection):
    """In-memory bidirectional stream over trio memory channels."""

    is_initiator: bool = False

    def __init__(self, send_chan: Any, recv_chan: Any) -> None:
        self._send = send_chan
        self._recv = recv_chan
        self._buf = bytearray()

    async def read(self, n: int | None = None) -> bytes:
        while not self._buf:
            try:
                self._buf.extend(await self._recv.receive())
            except trio.EndOfChannel:
                return b""
        if n is None:
            data = bytes(self._buf)
            self._buf.clear()
            return data
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data

    async def write(self, data: bytes) -> None:
        await self._send.send(bytes(data))

    async def close(self) -> None:
        await self._send.aclose()

    def get_remote_address(self) -> tuple[str, int] | None:
        return None

    def get_transport_addresses(self) -> list[Multiaddr]:
        return []

    def get_connection_type(self) -> ConnectionType:
        return ConnectionType.UNKNOWN


class _Capture(IRawConnection):
    """Wraps a connection and records every write, so we get the wire bytes."""

    is_initiator: bool = False

    def __init__(self, inner: _MemoryConn) -> None:
        self._inner = inner
        self.writes: list[bytes] = []

    async def read(self, n: int | None = None) -> bytes:
        return await self._inner.read(n)

    async def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))
        await self._inner.write(data)

    async def close(self) -> None:
        await self._inner.close()

    def get_remote_address(self) -> tuple[str, int] | None:
        return None

    def get_transport_addresses(self) -> list[Multiaddr]:
        return []

    def get_connection_type(self) -> ConnectionType:
        return ConnectionType.UNKNOWN


class _SeededKem:
    """
    ML-KEM-768 with FIPS 203 deterministic keygen and encapsulation.

    ``keygen()`` and ``encapsulate()`` consume seeds in order, so a given seed list
    always produces the same handshake. Matches the ``IKem`` protocol.
    """

    def __init__(self, keygen_seeds: list[bytes], encap_seeds: list[bytes]) -> None:
        from kyber_py.ml_kem import ML_KEM_768

        self._ml_kem = ML_KEM_768
        self._keygen_seeds = list(keygen_seeds)
        self._encap_seeds = list(encap_seeds)

    def keygen(self) -> tuple[bytes, bytes]:
        seed = self._keygen_seeds.pop(0)
        if len(seed) != 64:
            raise ValueError("ML-KEM key_derive needs a 64-byte seed (d || z)")
        ek, dk = self._ml_kem.key_derive(seed)
        return ek, dk

    def encapsulate(self, pk: bytes) -> tuple[bytes, bytes]:
        m = self._encap_seeds.pop(0)
        if len(m) != 32:
            raise ValueError("ML-KEM encapsulation needs a 32-byte message seed")
        ss, ct = self._ml_kem._encaps_internal(pk, m)  # FIPS 203 returns (ss, ct)
        return ct, ss  # IKem convention is (ct, ss)

    def decapsulate(self, ct: bytes, sk: bytes) -> bytes:
        return self._ml_kem.decaps(sk, ct)


class _SeededRandom:
    """Replacement for nacl.utils.random that returns fixed bytes in order."""

    def __init__(self, values: list[bytes]) -> None:
        self._values = list(values)

    def __call__(self, size: int = 32) -> bytes:
        v = self._values.pop(0)
        if len(v) != size:
            raise ValueError(f"seeded random wanted {size} bytes, seed has {len(v)}")
        return v


class _SplitRecorder:
    """
    Records the handshake hash and both transport keys at ``split()``.

    ``CipherState`` does not keep its key, so while ``split()`` runs the module's
    ``CipherState`` is swapped for a subclass that records the key it is built
    with. The recorded keys are therefore exactly the ones ``split()`` derived,
    not a re-derivation. Both peers split, so each call is recorded and the
    caller checks they agree.
    """

    def __init__(self) -> None:
        self.records: list[tuple[bytes, bytes, bytes]] = []
        self._real_split = noise_state.SymmetricState.split

    def __enter__(self) -> _SplitRecorder:
        real_split = self._real_split
        records = self.records

        def split(
            ss: noise_state.SymmetricState,
        ) -> tuple[noise_state.CipherState, noise_state.CipherState]:
            real_cipher_state = noise_state.CipherState
            keys: list[bytes] = []

            class _KeyRecordingCipherState(real_cipher_state):  # type: ignore[misc, valid-type]
                def __init__(self, key: bytes) -> None:
                    keys.append(key)
                    super().__init__(key)

            noise_state.CipherState = _KeyRecordingCipherState  # type: ignore[misc]
            try:
                result = real_split(ss)
            finally:
                noise_state.CipherState = real_cipher_state  # type: ignore[misc]
            if len(keys) != 2:
                raise RuntimeError(f"split() built {len(keys)} ciphers, expected 2")
            records.append((ss.h, keys[0], keys[1]))
            return result

        noise_state.SymmetricState.split = split  # type: ignore[assignment, method-assign]
        return self

    def __exit__(self, *exc: object) -> None:
        noise_state.SymmetricState.split = self._real_split  # type: ignore[method-assign]

    def agreed(self) -> tuple[bytes, bytes, bytes]:
        if len(self.records) != 2 or self.records[0] != self.records[1]:
            raise RuntimeError(
                f"expected both peers to split identically, got {len(self.records)} "
                "differing record(s)"
            )
        return self.records[0]


def _seed(base: int, n: int) -> bytes:
    """A visibly-synthetic seed: n copies of one byte. Never use for real keys."""
    return bytes([base]) * n


async def _run_one(index: int, base: int) -> dict[str, Any]:
    """Run one deterministic handshake and return its vector."""
    # --- deterministic key material -------------------------------------
    s_i_priv = _seed(base + 0x01, 32)  # initiator static X25519
    s_r_priv = _seed(base + 0x02, 32)  # responder static X25519
    e_i_priv = _seed(base + 0x03, 32)  # initiator ephemeral X25519
    e_r_priv = _seed(base + 0x04, 32)  # responder ephemeral X25519
    kem_seed = _seed(base + 0x05, 64)  # initiator ML-KEM keygen (d || z)
    encap_m = _seed(base + 0x06, 32)  # responder ML-KEM encapsulation

    init_ident = create_new_key_pair(_seed(base + 0x07, 32))
    resp_ident = create_new_key_pair(_seed(base + 0x08, 32))

    init_noise = X25519PrivateKey.from_bytes(s_i_priv)
    resp_noise = X25519PrivateKey.from_bytes(s_r_priv)

    init_pat = PatternXXhfs(
        local_peer=ID.from_pubkey(init_ident.public_key),
        libp2p_privkey=init_ident.private_key,
        noise_static_key=init_noise,
        kem=_SeededKem([kem_seed], []),
    )
    resp_pat = PatternXXhfs(
        local_peer=ID.from_pubkey(resp_ident.public_key),
        libp2p_privkey=resp_ident.private_key,
        noise_static_key=resp_noise,
        kem=_SeededKem([], [encap_m]),
    )

    a_send, a_recv = trio.open_memory_channel(math.inf)
    b_send, b_recv = trio.open_memory_channel(math.inf)
    init_cap = _Capture(_MemoryConn(a_send, b_recv))
    resp_cap = _Capture(_MemoryConn(b_send, a_recv))

    sessions: list[Any] = [None, None]
    recorder = _SplitRecorder()

    # Ephemerals are drawn in handshake order: initiator first, then responder.
    # The patch is applied inside the try so the finally always restores it;
    # assigning before the guard would leave nacl.utils.random seeded for the
    # rest of the process if anything below raised (harness audit F-007).
    real_random = nacl.utils.random
    try:
        nacl.utils.random = _SeededRandom(  # type: ignore[assignment]
            [e_i_priv, e_r_priv]
        )
        with recorder:
            async with trio.open_nursery() as nursery:

                async def _out() -> None:
                    sessions[0] = await init_pat.handshake_outbound(
                        init_cap, ID.from_pubkey(resp_ident.public_key)
                    )

                async def _in() -> None:
                    sessions[1] = await resp_pat.handshake_inbound(resp_cap)

                nursery.start_soon(_out)
                nursery.start_soon(_in)
    finally:
        nacl.utils.random = real_random  # type: ignore[assignment]

    # Writes are length-prefixed frames; strip the 2-byte prefix for the wire body.
    def body(frame: bytes) -> bytes:
        return frame[2:] if len(frame) > 2 else frame

    msg_a = body(init_cap.writes[0])
    msg_b = body(resp_cap.writes[0])
    msg_c = body(init_cap.writes[1])

    ek, _ = _SeededKem([kem_seed], []).keygen()
    handshake_hash, cs1_k, cs2_k = recorder.agreed()

    return {
        "vector_index": index,
        "description": (
            f"XXhfs ML-KEM-768 vector {index}: seeds derived from base 0x{base:02x}"
        ),
        "static_i_private": s_i_priv.hex(),
        "static_i_public": bytes(init_noise.get_public_key().to_bytes()).hex(),
        "static_r_private": s_r_priv.hex(),
        "static_r_public": bytes(resp_noise.get_public_key().to_bytes()).hex(),
        "ephemeral_dh_i_private": e_i_priv.hex(),
        "ephemeral_dh_i_public": bytes(crypto_scalarmult_base(e_i_priv)).hex(),
        "ephemeral_dh_r_private": e_r_priv.hex(),
        "ephemeral_dh_r_public": bytes(crypto_scalarmult_base(e_r_priv)).hex(),
        "kem_keygen_seed": kem_seed.hex(),
        "ephemeral_kem_i_public": ek.hex(),
        "kem_encap_seed": encap_m.hex(),
        "prologue": "",
        "msg_a": msg_a.hex(),
        "msg_b": msg_b.hex(),
        "msg_c": msg_c.hex(),
        "msg_a_bytes": len(msg_a),
        "msg_b_bytes": len(msg_b),
        "msg_c_bytes": len(msg_c),
        "handshake_hash": handshake_hash.hex(),
        "cs1_k": cs1_k.hex(),
        "cs2_k": cs2_k.hex(),
    }


async def _main_async(count: int, out: Path) -> None:
    vectors = []
    for i in range(count):
        v = await _run_one(i + 1, 0x10 + i * 0x10)
        vectors.append(v)
        print(
            f"  vector {v['vector_index']}: "
            f"A={v['msg_a_bytes']} B={v['msg_b_bytes']} C={v['msg_c_bytes']} bytes"
        )

    doc = {
        "protocol": PROTOCOL,
        "protocol_id": PROTOCOL_ID,
        "spec": "https://github.com/libp2p/specs/pull/723",
        "description": (
            "Deterministic test vectors for the Noise XXhfs handshake with raw "
            "ML-KEM-768. All key material is seeded for reproducibility; these keys "
            "MUST NOT be used outside testing."
        ),
        "generated_by": "py-libp2p scripts/gen_pq_test_vectors.py",
        "kem": "ML-KEM-768 (FIPS 203), via kyber-py",
        "kem_determinism": (
            "keygen uses FIPS 203 key_derive(d || z) with the 64-byte kem_keygen_seed; "
            "encapsulation uses _encaps_internal(ek, m) with the 32-byte kem_encap_seed"
        ),
        "message_layout": {
            "A": "e_pk(32) || e1_pk(1184)",
            "B": "e_pk(32) || enc_ct(1104) || enc_s(48) || enc_payload",
            "C": "enc_s(48) || enc_payload",
        },
        "tokens": {"A": "e, e1", "B": "e, ee, ekem1, s, es", "C": "s, se"},
        "note_on_payloads": (
            "Handshake payloads carry a libp2p identity signature over the static key, "
            "which depends on the identity keypair. msg_b and msg_c therefore also pin "
            "the identity keys used; see static_*/description."
        ),
        "vectors": vectors,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {len(vectors)} vectors to {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", "--count", type=int, default=5)
    ap.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("tests/fixtures/mlkem768-xxhfs-vectors.json"),
    )
    args = ap.parse_args()
    print(f"Generating {args.count} {PROTOCOL} vectors…")
    trio.run(_main_async, args.count, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
