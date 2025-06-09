from dataclasses import (
    dataclass,
)

from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)
from libp2p.crypto.serialization import (
    deserialize_public_key,
)

from .pb import noise_pb2 as noise_pb

SIGNED_DATA_PREFIX = "noise-libp2p-static-key:"


@dataclass
class NoiseHandshakePayload:
    id_pubkey: PublicKey
    id_sig: bytes
    early_data: bytes | None = None

    def serialize(self) -> bytes:
        msg = noise_pb.NoiseHandshakePayload(
            identity_key=self.id_pubkey.serialize(), identity_sig=self.id_sig
        )
        if self.early_data is not None:
            msg.data = self.early_data
        return msg.SerializeToString()

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
