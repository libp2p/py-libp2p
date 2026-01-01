import hashlib
import random

import base58
import multihash

from libp2p.crypto.rsa import (
    create_new_key_pair,
)
from libp2p.peer.id import (
    ID,
)

ALPHABETS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def test_eq_impl_for_bytes():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.choice(ALPHABETS)
    peer_id = ID(random_id_string.encode())
    assert peer_id == random_id_string.encode()


def test_pretty():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.choice(ALPHABETS)
    peer_id = ID(random_id_string.encode())
    actual = peer_id.pretty()
    expected = base58.b58encode(random_id_string).decode()

    assert actual == expected


def test_str_less_than_10():
    random_id_string = ""
    for _ in range(5):
        random_id_string += random.choice(ALPHABETS)
    peer_id = base58.b58encode(random_id_string).decode()
    expected = peer_id
    actual = ID(random_id_string.encode()).__str__()

    assert actual == expected


def test_str_more_than_10():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.choice(ALPHABETS)
    peer_id = base58.b58encode(random_id_string).decode()
    expected = peer_id
    actual = ID(random_id_string.encode()).__str__()

    assert actual == expected


def test_eq_true():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.choice(ALPHABETS)
    peer_id = ID(random_id_string.encode())

    assert peer_id == base58.b58encode(random_id_string).decode()
    assert peer_id == random_id_string.encode()
    assert peer_id == ID(random_id_string.encode())


def test_eq_false():
    peer_id = ID(b"efgh")
    other = ID(b"abcd")

    assert peer_id != other


def test_id_to_base58():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.choice(ALPHABETS)
    expected = base58.b58encode(random_id_string).decode()
    actual = ID(random_id_string.encode()).to_base58()

    assert actual == expected


def test_id_from_base58():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.choice(ALPHABETS)
    expected = ID(base58.b58decode(random_id_string))
    actual = ID.from_base58(random_id_string)

    assert actual == expected


def test_id_from_public_key():
    key_pair = create_new_key_pair()
    public_key = key_pair.public_key

    key_bin = public_key.serialize()
    # Use SHA2-256 hash (since key is larger than MAX_INLINE_KEY_LENGTH)
    digest = hashlib.sha256(key_bin).digest()
    mh_bytes = multihash.encode(digest, "sha2-256")
    expected = ID(mh_bytes)

    actual = ID.from_pubkey(public_key)

    assert actual == expected
