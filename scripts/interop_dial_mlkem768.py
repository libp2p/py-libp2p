#!/usr/bin/env python3
"""
Interop dialer: Python -> Rust noise_hfs_listener.

Speaks Noise_XXhfs_25519+ML-KEM-768_ChaChaPoly_SHA256 (NOT X-Wing).
Raw ML-KEM-768 without the extra X25519 wrapper used by the X-Wing variant.

Usage:
    # Terminal 1: start Rust listener
    cargo run --example noise_hfs_listener --features mlkem-hfs -- 9999

    # Terminal 2: dial from Python
    cd py-libp2p
    python scripts/interop_dial_mlkem768.py --port 9999
"""

import argparse
import asyncio
import hashlib
import hmac
import logging
import struct
import sys
from typing import cast

import anyio
import anyio.abc
from kyber_py.ml_kem import ML_KEM_768
from nacl.bindings import crypto_scalarmult, crypto_scalarmult_base
import nacl.utils
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from libp2p.crypto.ed25519 import create_new_key_pair as ed25519_keypair
from libp2p.crypto.x25519 import X25519PublicKey, create_new_key_pair as x25519_keypair
from libp2p.io.abc import ReadWriteCloser
from libp2p.peer.id import ID
from libp2p.security.noise.io import NoisePacketReadWriter
from libp2p.security.noise.messages import (
    NoiseHandshakePayload,
    make_handshake_payload_sig,
    verify_handshake_payload_sig,
)
from libp2p.security.noise.exceptions import InvalidSignature

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("interop_dial_mlkem768")

# ---------------------------------------------------------------------------
# Protocol constants for Noise_XXhfs_25519+ML-KEM-768_ChaChaPoly_SHA256
# ---------------------------------------------------------------------------
PROTOCOL_NAME = b"Noise_XXhfs_25519+ML-KEM-768_ChaChaPoly_SHA256"

ML_KEM_768_PK_SIZE = 1184   # ML-KEM-768 encapsulation key
ML_KEM_768_CT_SIZE = 1088   # ML-KEM-768 ciphertext
ML_KEM_768_SS_SIZE = 32     # ML-KEM-768 shared secret
X25519_SIZE = 32             # X25519 public/private key size
AEAD_TAG = 16                # Poly1305 tag length
KEY_LEN = 32                 # ChaCha20 key length
HASH_LEN = 32                # SHA-256 output length

# Encrypted sizes (plaintext + AEAD tag)
_CT_ENC_SIZE = ML_KEM_768_CT_SIZE + AEAD_TAG   # 1088 + 16 = 1104
_S_ENC_SIZE = X25519_SIZE + AEAD_TAG            # 32   + 16 = 48

HOST = "127.0.0.1"


# ---------------------------------------------------------------------------
# Noise symmetric state for ML-KEM-768 variant
# ---------------------------------------------------------------------------

def _hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def _hkdf(chaining_key: bytes, ikm: bytes, n: int) -> tuple[bytes, ...]:
    """Noise HKDF producing n outputs (2 or 3), each 32 bytes."""
    temp_k = _hmac_sha256(chaining_key, ikm)
    out1 = _hmac_sha256(temp_k, b"\x01")
    out2 = _hmac_sha256(temp_k, out1 + b"\x02")
    if n == 2:
        return out1, out2
    out3 = _hmac_sha256(temp_k, out2 + b"\x03")
    return out1, out2, out3


def _nonce_bytes(n: int) -> bytes:
    """Encode Noise nonce: 4 zero bytes + 8-byte little-endian counter."""
    return b"\x00" * 4 + struct.pack("<Q", n)


class CipherStateMLKEM:
    """Noise CipherState using ChaCha20-Poly1305."""

    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_LEN:
            raise ValueError(f"Key must be {KEY_LEN} bytes, got {len(key)}")
        self._cipher = ChaCha20Poly1305(key)
        self.n = 0

    def encrypt_with_ad(self, ad: bytes, plaintext: bytes) -> bytes:
        ct = self._cipher.encrypt(_nonce_bytes(self.n), plaintext, ad)
        self.n += 1
        return ct

    def decrypt_with_ad(self, ad: bytes, ciphertext: bytes) -> bytes:
        pt = self._cipher.decrypt(_nonce_bytes(self.n), ciphertext, ad)
        self.n += 1
        return pt


class SymmetricStateMLKEM:
    """
    Noise SymmetricState initialised with the ML-KEM-768 protocol name.

    Identical algorithm to SymmetricState in noise_state.py but bound to
    Noise_XXhfs_25519+ML-KEM-768_ChaChaPoly_SHA256 rather than the X-Wing
    protocol name. The protocol name is cryptographically bound to every
    derived key via the initial ck/h values.
    """

    def __init__(self) -> None:
        # Protocol name > 32 bytes so h = HASH(protocol_name)
        digest = hashlib.sha256(PROTOCOL_NAME).digest()
        self.ck: bytes = digest
        self.h: bytes = digest
        self._cs: CipherStateMLKEM | None = None

    def mix_hash(self, data: bytes) -> None:
        """h = SHA-256(h || data)"""
        self.h = hashlib.sha256(self.h + data).digest()

    def mix_key(self, ikm: bytes) -> None:
        """Update chaining key and set a new cipher key via 2-output HKDF."""
        self.ck, temp_k = _hkdf(self.ck, ikm, 2)
        self._cs = CipherStateMLKEM(temp_k)

    def encrypt_and_hash(self, plaintext: bytes) -> bytes:
        """
        AEAD-encrypt plaintext then mix the ciphertext into h.

        When no cipher key is established yet, behaves as mix_hash (returns
        the plaintext unchanged, which for an empty payload means b"").
        """
        if self._cs is None:
            self.mix_hash(plaintext)
            return plaintext
        ct = self._cs.encrypt_with_ad(self.h, plaintext)
        self.mix_hash(ct)
        return ct

    def decrypt_and_hash(self, ciphertext: bytes) -> bytes:
        """AEAD-decrypt ciphertext then mix the ciphertext into h."""
        if self._cs is None:
            self.mix_hash(ciphertext)
            return ciphertext
        pt = self._cs.decrypt_with_ad(self.h, ciphertext)
        self.mix_hash(ciphertext)
        return pt

    def split(self) -> tuple[CipherStateMLKEM, CipherStateMLKEM]:
        """
        Derive two transport CipherStates at the end of the handshake.

        Returns (cs_initiator_send, cs_initiator_recv).
        """
        temp_k1, temp_k2 = _hkdf(self.ck, b"", 2)
        return CipherStateMLKEM(temp_k1), CipherStateMLKEM(temp_k2)


# ---------------------------------------------------------------------------
# Minimal IRawConnection wrapper over anyio ByteStream
# ---------------------------------------------------------------------------

class RawTCPConn:
    """
    Minimal IRawConnection wrapping an anyio SocketStream.

    Adapts anyio's ByteStream to the read/write/close interface expected
    by NoisePacketReadWriter.
    """

    is_initiator: bool = True

    def __init__(self, stream: anyio.abc.ByteStream) -> None:
        self._stream = stream

    async def read(self, n: int | None = None) -> bytes:
        if n is None:
            return await self._stream.receive(65536)
        return await self._stream.receive(n)

    async def write(self, data: bytes) -> None:
        await self._stream.send(data)

    async def close(self) -> None:
        await self._stream.aclose()

    def get_transport_addresses(self) -> list:
        return []


# ---------------------------------------------------------------------------
# Transport read/writer after handshake completes
# ---------------------------------------------------------------------------

class MLKEMTransportReadWriter:
    """Post-handshake transport using independent send/recv CipherStates."""

    def __init__(
        self,
        conn: RawTCPConn,
        send_cs: CipherStateMLKEM,
        recv_cs: CipherStateMLKEM,
    ) -> None:
        self._pkt = NoisePacketReadWriter(cast(ReadWriteCloser, conn))
        self._send_cs = send_cs
        self._recv_cs = recv_cs

    async def write(self, data: bytes) -> None:
        ct = self._send_cs.encrypt_with_ad(b"", data)
        await self._pkt.write_msg(ct)

    async def read(self) -> bytes:
        ct = await self._pkt.read_msg()
        return self._recv_cs.decrypt_with_ad(b"", ct)


# ---------------------------------------------------------------------------
# ML-KEM-768 helpers via kyber-py (pure Python, no native lib required)
# NOTE: ML_KEM_768.encaps() returns (shared_secret, ciphertext) -- reversed
#       from the liboqs convention. Handle accordingly.
# ---------------------------------------------------------------------------

def mlkem768_keygen() -> tuple[bytes, bytes]:
    """Generate an ML-KEM-768 keypair. Returns (encapsulation_key, decapsulation_key)."""
    pk, sk = ML_KEM_768.keygen()
    return pk, sk


def mlkem768_decap(ct: bytes, sk: bytes) -> bytes:
    """Decapsulate ML-KEM-768 ciphertext. Returns 32-byte shared secret."""
    return ML_KEM_768.decaps(sk, ct)


# ---------------------------------------------------------------------------
# Handshake initiator
# ---------------------------------------------------------------------------

async def run_handshake_initiator(
    conn: RawTCPConn,
    libp2p_kp: object,
    noise_static_privkey: object,
) -> tuple[MLKEMTransportReadWriter, ID]:
    """
    Run the initiator side of Noise_XXhfs_25519+ML-KEM-768_ChaChaPoly_SHA256.

    Message layout
    --------------
    msg1 (initiator -> responder): e_pk(32) || e1_pk(1184)
    msg2 (responder -> initiator): e_pk(32) || enc_ekem1_ct(1104)
                                   || enc_s(48) || enc_payload
    msg3 (initiator -> responder): enc_s(48) || enc_payload

    Token sequence
    --------------
    msg1: e, e1
    msg2: e, ee, ekem1, s, es
    msg3: s, se

    Returns:
        (transport, remote_peer_id)
    """
    ss = SymmetricStateMLKEM()
    # MixHash(prologue=empty) -- required by Noise spec even when empty
    ss.mix_hash(b"")
    pkt = NoisePacketReadWriter(cast(ReadWriteCloser, conn))

    # ---- Message 1: e, e1 -----------------------------------------------
    # e: ephemeral X25519 key
    e_sk = nacl.utils.random(X25519_SIZE)
    e_pk = bytes(crypto_scalarmult_base(e_sk))
    ss.mix_hash(e_pk)
    logger.debug("msg1: generated ephemeral X25519 e_pk (%d B)", len(e_pk))

    # e1: ephemeral ML-KEM-768 keypair (encapsulation key only sent)
    e1_pk, e1_sk = mlkem768_keygen()
    ss.mix_hash(e1_pk)
    logger.debug("msg1: generated ML-KEM-768 e1_pk (%d B)", len(e1_pk))

    # No payload -- encrypt_and_hash(b"") with no key = just mix_hash(b"")
    enc_payload_1 = ss.encrypt_and_hash(b"")

    msg1 = e_pk + e1_pk + enc_payload_1
    await pkt.write_msg(msg1)
    logger.info("msg1 sent: %d bytes (e_pk=%d, e1_pk=%d)", len(msg1), len(e_pk), len(e1_pk))

    # ---- Message 2: e, ee, ekem1, s, es ---------------------------------
    msg2 = await pkt.read_msg()
    logger.info("msg2 received: %d bytes", len(msg2))
    offset = 0

    # e: responder's ephemeral X25519 public key
    resp_e_pk = msg2[offset : offset + X25519_SIZE]
    offset += X25519_SIZE
    ss.mix_hash(resp_e_pk)

    # ee: DH(e_init, e_resp)
    dh_ee = bytes(crypto_scalarmult(e_sk, resp_e_pk))
    ss.mix_key(dh_ee)
    logger.debug("msg2: processed 'ee' DH token")

    # ekem1: receive encrypted ML-KEM-768 ciphertext, decap, mix_key
    enc_ct = msg2[offset : offset + _CT_ENC_SIZE]
    offset += _CT_ENC_SIZE
    ct = ss.decrypt_and_hash(enc_ct)   # decrypt under ee-derived key
    if len(ct) != ML_KEM_768_CT_SIZE:
        raise ValueError(
            f"ekem1: expected {ML_KEM_768_CT_SIZE}-byte ML-KEM-768 ct, got {len(ct)}"
        )
    ss_kem = mlkem768_decap(ct, e1_sk)
    ss.mix_key(ss_kem)
    logger.debug("msg2: processed 'ekem1' token, ss_kem=%s", ss_kem.hex())

    # s: decrypt responder's static X25519 public key
    enc_s = msg2[offset : offset + _S_ENC_SIZE]
    offset += _S_ENC_SIZE
    resp_s_pk_bytes = ss.decrypt_and_hash(enc_s)
    if len(resp_s_pk_bytes) != X25519_SIZE:
        raise ValueError(
            f"s: expected {X25519_SIZE}-byte static pk, got {len(resp_s_pk_bytes)}"
        )
    resp_s_pk = X25519PublicKey.from_bytes(resp_s_pk_bytes)
    logger.debug("msg2: decrypted responder static pk")

    # es: DH(e_init, s_resp)
    dh_es = bytes(crypto_scalarmult(e_sk, resp_s_pk_bytes))
    ss.mix_key(dh_es)
    logger.debug("msg2: processed 'es' DH token")

    # Decrypt and verify responder's identity payload
    resp_payload_bytes = ss.decrypt_and_hash(msg2[offset:])
    resp_payload = NoiseHandshakePayload.deserialize(resp_payload_bytes)

    if not verify_handshake_payload_sig(resp_payload, resp_s_pk):
        raise InvalidSignature("Responder identity signature verification failed")

    resp_peer_id = ID.from_pubkey(resp_payload.id_pubkey)
    logger.info("msg2: responder identity verified, peer=%s", resp_peer_id)

    # ---- Message 3: s, se -----------------------------------------------
    # s: encrypt our static X25519 public key
    static_pk_bytes = noise_static_privkey.get_public_key().to_bytes()
    enc_s_3 = ss.encrypt_and_hash(static_pk_bytes)

    # se: DH(s_init, e_resp)
    dh_se = bytes(crypto_scalarmult(noise_static_privkey.to_bytes(), resp_e_pk))
    ss.mix_key(dh_se)
    logger.debug("msg3: processed 'se' DH token")

    # Build and encrypt our identity payload
    static_pubkey = noise_static_privkey.get_public_key()
    sig = make_handshake_payload_sig(libp2p_kp.private_key, static_pubkey)
    our_payload = NoiseHandshakePayload(
        id_pubkey=libp2p_kp.public_key,
        id_sig=sig,
    ).serialize()
    enc_payload_3 = ss.encrypt_and_hash(our_payload)

    msg3 = enc_s_3 + enc_payload_3
    await pkt.write_msg(msg3)
    logger.info("msg3 sent: %d bytes", len(msg3))

    # ---- Split transport keys -------------------------------------------
    cs1, cs2 = ss.split()
    # Initiator: send with cs1, receive with cs2
    transport = MLKEMTransportReadWriter(conn, send_cs=cs1, recv_cs=cs2)
    return transport, resp_peer_id


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def main(port: int) -> None:
    # Generate libp2p identity key (Ed25519) and Noise static key (X25519)
    libp2p_kp = ed25519_keypair()
    local_peer = ID.from_pubkey(libp2p_kp.public_key)
    noise_kp = x25519_keypair()
    noise_static_privkey = noise_kp.private_key

    logger.info("Local peer ID: %s", local_peer)
    logger.info(
        "Protocol: %s", PROTOCOL_NAME.decode()
    )

    logger.info("Connecting to Rust listener at %s:%d", HOST, port)
    async with await anyio.connect_tcp(HOST, port) as stream:
        conn = RawTCPConn(stream)
        logger.info("TCP connection established")

        transport, resp_peer_id = await run_handshake_initiator(
            conn, libp2p_kp, noise_static_privkey
        )

        print(f"PEER {resp_peer_id}")
        print("HANDSHAKE COMPLETE")
        logger.info("Handshake complete. Remote peer: %s", resp_peer_id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dial a Rust noise_hfs_listener using ML-KEM-768 (no X-Wing wrapper).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9999,
        help="TCP port the Rust listener is bound to (default: 9999)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    anyio.run(main, args.port)
