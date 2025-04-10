from dataclasses import (
    dataclass,
)
import logging

from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)
from libp2p.crypto.pb import (
    crypto_pb2,
)
from libp2p.crypto.serialization import (
    deserialize_public_key,
)

from .pb import noise_pb2 as noise_pb

SIGNED_DATA_PREFIX = "noise-libp2p-static-key:"


def serialize_public_key(pubkey: PublicKey) -> bytes:
    pubkey_proto = crypto_pb2.PublicKey()
    key_bytes = pubkey.to_bytes()
    logging.debug(f"Raw public key bytes: {key_bytes.hex()}, length: {len(key_bytes)}")
    # Validate Ed25519 key (basic check)
    if len(key_bytes) != 32:
        raise ValueError(f"Invalid Ed25519 key length: {len(key_bytes)}")
    pubkey_proto.key_type = pubkey.get_type().value
    pubkey_proto.data = key_bytes
    serialized = pubkey_proto.SerializeToString()
    logging.debug(f"Serialized pubkey: {serialized.hex()}")
    return serialized


@dataclass
class NoiseHandshakePayload:
    id_pubkey: PublicKey
    id_sig: bytes
    early_data: bytes = None

    def serialize(self) -> bytes:
        pubkey_serialized = serialize_public_key(self.id_pubkey)
        msg = noise_pb.NoiseHandshakePayload(
            identity_key=pubkey_serialized, identity_sig=self.id_sig
        )
        if self.early_data is not None:
            msg.data = self.early_data
        serialized = msg.SerializeToString()
        logging.debug(f"Serialized payload: {serialized.hex()}")
        return serialized

    @classmethod
    def deserialize(cls, protobuf_bytes: bytes) -> "NoiseHandshakePayload":
        msg = noise_pb.NoiseHandshakePayload.FromString(protobuf_bytes)
        return cls(
            id_pubkey=deserialize_public_key(msg.identity_key),
            id_sig=msg.identity_sig,
            early_data=msg.data if msg.data != b"" else None,
        )


def make_data_to_be_signed(noise_static_pubkey: PublicKey) -> bytes:
    prefix_bytes = SIGNED_DATA_PREFIX.encode("utf-8")
    return prefix_bytes + noise_static_pubkey.to_bytes()


def make_handshake_payload_sig(
    id_privkey: PrivateKey, noise_static_pubkey: PublicKey
) -> bytes:
    data = make_data_to_be_signed(noise_static_pubkey)
    return id_privkey.sign(data)


def verify_handshake_payload_sig(
    payload: NoiseHandshakePayload, noise_static_pubkey: PublicKey
) -> bool:
    """
    Verify if the signature
        1. is composed of the data `SIGNED_DATA_PREFIX`++`noise_static_pubkey` and
        2. signed by the private key corresponding to `id_pubkey`
    """
    expected_data = make_data_to_be_signed(noise_static_pubkey)
    return payload.id_pubkey.verify(expected_data, payload.id_sig)
