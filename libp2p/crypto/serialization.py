from libp2p.crypto.keys import KeyType, PrivateKey, PublicKey
from libp2p.crypto.secp256k1 import Secp256k1PrivateKey, Secp256k1PublicKey

key_type_to_public_key_deserializer = {
    KeyType.Secp256k1.value: Secp256k1PublicKey.from_bytes
}

key_type_to_private_key_deserializer = {
    KeyType.Secp256k1.value: Secp256k1PrivateKey.from_bytes
}


def deserialize_public_key(data: bytes) -> PublicKey:
    f = PublicKey.deserialize_from_protobuf(data)
    deserializer = key_type_to_public_key_deserializer[f.key_type]
    return deserializer(f.data)


def deserialize_private_key(data: bytes) -> PrivateKey:
    f = PrivateKey.deserialize_from_protobuf(data)
    deserializer = key_type_to_private_key_deserializer[f.key_type]
    return deserializer(f.data)
