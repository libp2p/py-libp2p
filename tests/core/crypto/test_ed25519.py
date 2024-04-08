from libp2p.crypto.ed25519 import (
    create_new_key_pair,
)
from libp2p.crypto.serialization import (
    deserialize_private_key,
    deserialize_public_key,
)


def test_public_key_serialize_deserialize_round_trip():
    key_pair = create_new_key_pair()
    public_key = key_pair.public_key

    public_key_bytes = public_key.serialize()
    another_public_key = deserialize_public_key(public_key_bytes)

    assert public_key == another_public_key


def test_private_key_serialize_deserialize_round_trip():
    key_pair = create_new_key_pair()
    private_key = key_pair.private_key

    private_key_bytes = private_key.serialize()
    another_private_key = deserialize_private_key(private_key_bytes)

    assert private_key == another_private_key
