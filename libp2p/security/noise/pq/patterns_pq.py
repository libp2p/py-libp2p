"""
XXhfs Noise handshake pattern for post-quantum security.

Implements Noise_XXhfs_25519+XWing_ChaChaPoly_SHA256: a three-message
handshake that adds X-Wing KEM tokens to the classical Noise XX pattern
for hybrid post-quantum forward secrecy.

Message layout (wire bytes, inside 2-byte length-prefixed frames):
  A (initiator -> responder): e_pk(32) || e1_pk(1216)         = 1248 B
  B (responder -> initiator): e_pk(32) || enc_ct(1136)
                               || enc_s(48) || enc_payload
  C (initiator -> responder): enc_s(48) || enc_payload

Token sequence:
  A: e, e1                       (no symmetric key yet, plain mix_hash)
  B: e, ee, ekem1, s, es         (ekem1 = encrypt(ct) then mix_key(ss_kem))
  C: s, se

Transport keys after split():
  Initiator:  encrypt=cs1, decrypt=cs2
  Responder:  encrypt=cs2, decrypt=cs1
"""

import logging
from typing import cast

import nacl.utils
from nacl.bindings import (
    crypto_scalarmult,
    crypto_scalarmult_base,
)

from libp2p.abc import (
    IRawConnection,
    ISecureConn,
)
from libp2p.crypto.keys import PrivateKey
from libp2p.crypto.x25519 import X25519PublicKey
from libp2p.io.abc import (
    EncryptedMsgReadWriter,
    ReadWriteCloser,
)
from libp2p.peer.id import ID
from libp2p.security.secure_session import SecureSession

from ..exceptions import (
    InvalidSignature,
    PeerIDMismatchesPubkey,
)
from ..io import NoisePacketReadWriter
from ..messages import (
    NoiseHandshakePayload,
    make_handshake_payload_sig,
    verify_handshake_payload_sig,
)
from .kem import (
    IKem,
    XWING_CT_SIZE,
    XWING_PK_SIZE,
    XWingKem,
)
from .noise_state import (
    CipherState,
    SymmetricState,
)

logger = logging.getLogger(__name__)

# Size constants
_X25519_SIZE = 32
_AEAD_TAG = 16
_KEM_CT_ENC_SIZE = XWING_CT_SIZE + _AEAD_TAG   # 1120 + 16 = 1136
_S_ENC_SIZE = _X25519_SIZE + _AEAD_TAG           # 32   + 16 = 48


class PQTransportReadWriter(EncryptedMsgReadWriter):
    """Post-handshake transport that encrypts/decrypts with PQC CipherStates.

    Each direction uses its own CipherState with an independent nonce counter,
    matching the Noise spec for transport-phase messages.
    """

    def __init__(
        self,
        conn: IRawConnection,
        send_cs: CipherState,
        recv_cs: CipherState,
    ) -> None:
        super().__init__(conn)  # sets self.conn for address delegation
        self._packet_rw = NoisePacketReadWriter(cast(ReadWriteCloser, conn))
        self._send_cs = send_cs
        self._recv_cs = recv_cs

    def encrypt(self, data: bytes) -> bytes:
        return self._send_cs.encrypt_with_ad(b"", data)

    def decrypt(self, data: bytes) -> bytes:
        return self._recv_cs.decrypt_with_ad(b"", data)

    async def write_msg(self, msg: bytes) -> None:
        await self._packet_rw.write_msg(self.encrypt(msg))

    async def read_msg(self) -> bytes:
        return self.decrypt(await self._packet_rw.read_msg())

    async def close(self) -> None:
        await self._packet_rw.close()


class PatternXXhfs:
    """Noise XXhfs handshake pattern with X-Wing hybrid KEM.

    Provides mutual authentication (libp2p identity signatures) and
    hybrid post-quantum forward secrecy via the X-Wing KEM (ML-KEM-768
    + X25519) alongside the classical X25519 DH exchange.
    """

    PROTOCOL_NAME = b"Noise_XXhfs_25519+XWing_ChaChaPoly_SHA256"

    def __init__(
        self,
        local_peer: ID,
        libp2p_privkey: PrivateKey,
        noise_static_key: PrivateKey,
        kem: IKem | None = None,
        early_data: bytes | None = None,
    ) -> None:
        self.local_peer = local_peer
        self.libp2p_privkey = libp2p_privkey
        self.noise_static_key = noise_static_key
        self.kem: IKem = kem if kem is not None else XWingKem()
        self.early_data = early_data

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _static_pk_bytes(self) -> bytes:
        """Return the raw 32-byte X25519 static public key."""
        return self.noise_static_key.get_public_key().to_bytes()

    def _static_sk_bytes(self) -> bytes:
        """Return the raw 32-byte X25519 static private key."""
        return self.noise_static_key.to_bytes()

    def _make_payload(self) -> bytes:
        """Serialize a libp2p NoiseHandshakePayload (id_pubkey + id_sig)."""
        static_pubkey = self.noise_static_key.get_public_key()
        sig = make_handshake_payload_sig(self.libp2p_privkey, static_pubkey)
        return NoiseHandshakePayload(
            id_pubkey=self.libp2p_privkey.get_public_key(),
            id_sig=sig,
        ).serialize()

    # ------------------------------------------------------------------
    # Initiator (outbound)
    # ------------------------------------------------------------------

    async def handshake_outbound(
        self, conn: IRawConnection, remote_peer: ID | None
    ) -> ISecureConn:
        """Run the initiator side of the XXhfs handshake.

        Args:
            conn:        Raw underlying connection.
            remote_peer: Expected peer ID of the responder (verified against
                         the responder's libp2p identity signature).
                         Pass ``None`` to accept any peer identity (useful
                         for interop tests where the remote peer ID is
                         not known in advance).

        Returns:
            SecureSession ready for post-handshake transport.

        Raises:
            PeerIDMismatchesPubkey: If the responder's peer ID does not match
                                    ``remote_peer`` (only raised when non-None).
            InvalidSignature:       If the responder's identity signature
                                    is invalid.

        """
        ss = SymmetricState()
        ss.mix_hash(b"")  # MixHash(prologue=empty) — required by Noise spec even when empty
        pkt = NoisePacketReadWriter(cast(ReadWriteCloser, conn))

        # ---- Message A: e, e1 ----------------------------------------
        # e: ephemeral X25519
        e_sk = nacl.utils.random(_X25519_SIZE)
        e_pk = bytes(crypto_scalarmult_base(e_sk))
        ss.mix_hash(e_pk)
        logger.debug("handshake_outbound: msg A – generated ephemeral X25519")

        # e1: ephemeral X-Wing KEM keypair
        e1_pk, e1_sk = self.kem.keygen()
        ss.mix_hash(e1_pk)
        logger.debug("handshake_outbound: msg A – generated X-Wing KEM keypair")

        # Empty payload (no cipher key yet; encrypt_and_hash = mix_hash + identity)
        enc_payload_a = ss.encrypt_and_hash(b"")
        await pkt.write_msg(e_pk + e1_pk + enc_payload_a)
        logger.debug("handshake_outbound: msg A sent (%d B)", len(e_pk) + len(e1_pk))

        # ---- Message B: e, ee, ekem1, s, es --------------------------
        msg_b = await pkt.read_msg()
        offset = 0
        logger.debug("handshake_outbound: msg B received (%d B)", len(msg_b))

        # e: responder's ephemeral X25519 public key
        resp_e_pk = msg_b[offset : offset + _X25519_SIZE]
        offset += _X25519_SIZE
        ss.mix_hash(resp_e_pk)

        # ee: DH(e_init, e_resp)
        dh_ee = bytes(crypto_scalarmult(e_sk, resp_e_pk))
        ss.mix_key(dh_ee)

        # ekem1: decrypt KEM ciphertext, then mix KEM shared secret
        enc_ct = msg_b[offset : offset + _KEM_CT_ENC_SIZE]
        offset += _KEM_CT_ENC_SIZE
        ct = ss.decrypt_and_hash(enc_ct)          # decrypt with ee-derived key
        ss_kem = self.kem.decapsulate(ct, e1_sk)  # recover KEM shared secret
        ss.mix_key(ss_kem)

        # s: decrypt responder's static public key
        enc_s = msg_b[offset : offset + _S_ENC_SIZE]
        offset += _S_ENC_SIZE
        resp_s_pk_bytes = ss.decrypt_and_hash(enc_s)
        resp_s_pk = X25519PublicKey.from_bytes(resp_s_pk_bytes)

        # es: DH(e_init, s_resp)
        dh_es = bytes(crypto_scalarmult(e_sk, resp_s_pk_bytes))
        ss.mix_key(dh_es)

        # Decrypt responder's handshake payload
        resp_payload_bytes = ss.decrypt_and_hash(msg_b[offset:])
        resp_payload = NoiseHandshakePayload.deserialize(resp_payload_bytes)

        # Verify responder's libp2p identity signature
        if not verify_handshake_payload_sig(resp_payload, resp_s_pk):
            raise InvalidSignature
        resp_peer_id = ID.from_pubkey(resp_payload.id_pubkey)
        if remote_peer is not None and resp_peer_id != remote_peer:
            raise PeerIDMismatchesPubkey(
                f"peer ID mismatch: expected {remote_peer}, got {resp_peer_id}"
            )

        # ---- Message C: s, se ----------------------------------------
        # s: encrypt our static public key
        enc_s_c = ss.encrypt_and_hash(self._static_pk_bytes())

        # se: DH(s_init, e_resp)
        dh_se = bytes(crypto_scalarmult(self._static_sk_bytes(), resp_e_pk))
        ss.mix_key(dh_se)

        # Encrypt our handshake payload
        enc_payload_c = ss.encrypt_and_hash(self._make_payload())
        await pkt.write_msg(enc_s_c + enc_payload_c)
        logger.debug("handshake_outbound: msg C sent")

        # ---- Split and return ----------------------------------------
        cs1, cs2 = ss.split()
        transport = PQTransportReadWriter(conn, send_cs=cs1, recv_cs=cs2)
        return SecureSession(
            local_peer=self.local_peer,
            local_private_key=self.libp2p_privkey,
            remote_peer=resp_peer_id,
            remote_permanent_pubkey=resp_s_pk,
            is_initiator=True,
            conn=transport,
        )

    # ------------------------------------------------------------------
    # Responder (inbound)
    # ------------------------------------------------------------------

    async def handshake_inbound(self, conn: IRawConnection) -> ISecureConn:
        """Run the responder side of the XXhfs handshake.

        Args:
            conn: Raw underlying connection.

        Returns:
            SecureSession ready for post-handshake transport.

        Raises:
            InvalidSignature: If the initiator's identity signature is invalid.

        """
        ss = SymmetricState()
        ss.mix_hash(b"")  # MixHash(prologue=empty) — required by Noise spec even when empty
        pkt = NoisePacketReadWriter(cast(ReadWriteCloser, conn))

        # ---- Message A: receive e, e1 --------------------------------
        msg_a = await pkt.read_msg()
        logger.debug("handshake_inbound: msg A received (%d B)", len(msg_a))
        offset = 0

        # e: initiator's ephemeral X25519 public key
        init_e_pk = msg_a[offset : offset + _X25519_SIZE]
        offset += _X25519_SIZE
        ss.mix_hash(init_e_pk)

        # e1: initiator's X-Wing KEM public key
        init_e1_pk = msg_a[offset : offset + XWING_PK_SIZE]
        offset += XWING_PK_SIZE
        ss.mix_hash(init_e1_pk)

        # Empty payload (no cipher key yet)
        ss.decrypt_and_hash(msg_a[offset:])  # mix_hash(b"")

        # ---- Message B: e, ee, ekem1, s, es --------------------------
        # e: generate our ephemeral X25519
        e_sk = nacl.utils.random(_X25519_SIZE)
        e_pk = bytes(crypto_scalarmult_base(e_sk))
        ss.mix_hash(e_pk)

        # ee: DH(e_resp, e_init)
        dh_ee = bytes(crypto_scalarmult(e_sk, init_e_pk))
        ss.mix_key(dh_ee)

        # ekem1: encapsulate to initiator's e1, encrypt ct, then mix ss_kem
        ct, ss_kem_bytes = self.kem.encapsulate(init_e1_pk)
        enc_ct = ss.encrypt_and_hash(ct)   # encrypt with ee-derived key
        ss.mix_key(ss_kem_bytes)           # now ss_kem strengthens key material

        # s: encrypt our static public key
        enc_s = ss.encrypt_and_hash(self._static_pk_bytes())

        # es: DH(s_resp, e_init)
        dh_es = bytes(crypto_scalarmult(self._static_sk_bytes(), init_e_pk))
        ss.mix_key(dh_es)

        # Encrypt our handshake payload
        enc_payload_b = ss.encrypt_and_hash(self._make_payload())

        await pkt.write_msg(e_pk + enc_ct + enc_s + enc_payload_b)
        logger.debug("handshake_inbound: msg B sent")

        # ---- Message C: receive s, se --------------------------------
        msg_c = await pkt.read_msg()
        logger.debug("handshake_inbound: msg C received (%d B)", len(msg_c))
        offset = 0

        # s: decrypt initiator's static public key
        enc_s_c = msg_c[offset : offset + _S_ENC_SIZE]
        offset += _S_ENC_SIZE
        init_s_pk_bytes = ss.decrypt_and_hash(enc_s_c)

        # se: DH(e_resp, s_init)
        dh_se = bytes(crypto_scalarmult(e_sk, init_s_pk_bytes))
        ss.mix_key(dh_se)

        # Decrypt initiator's handshake payload
        init_payload_bytes = ss.decrypt_and_hash(msg_c[offset:])
        init_payload = NoiseHandshakePayload.deserialize(init_payload_bytes)

        # Verify initiator's libp2p identity signature
        init_s_pk = X25519PublicKey.from_bytes(init_s_pk_bytes)
        if not verify_handshake_payload_sig(init_payload, init_s_pk):
            raise InvalidSignature
        init_peer_id = ID.from_pubkey(init_payload.id_pubkey)

        # ---- Split and return ----------------------------------------
        cs1, cs2 = ss.split()
        transport = PQTransportReadWriter(conn, send_cs=cs2, recv_cs=cs1)
        return SecureSession(
            local_peer=self.local_peer,
            local_private_key=self.libp2p_privkey,
            remote_peer=init_peer_id,
            remote_permanent_pubkey=init_s_pk,
            is_initiator=False,
            conn=transport,
        )
