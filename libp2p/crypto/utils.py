from .keys import PublicKey
from .pb import crypto_pb2 as protobuf
from .rsa import RSAPublicKey
from .secp256k1 import Secp256k1PublicKey


def pubkey_from_protobuf(pubkey_pb: protobuf.PublicKey) -> PublicKey:
    if pubkey_pb.key_type == protobuf.RSA:
        return RSAPublicKey.from_bytes(pubkey_pb.data)
    # TODO: Test against secp256k1 keys
    elif pubkey_pb.key_type == protobuf.Secp256k1:
        return Secp256k1PublicKey.from_bytes(pubkey_pb.data)
    # TODO: Support `Ed25519` and `ECDSA` in the future?
    else:
        raise ValueError(
            f"unsupported key_type={pubkey_pb.key_type}, data={pubkey_pb.data!r}"
        )
