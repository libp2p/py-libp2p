import random

import pytest
import base58
import multibase
import multihash

from libp2p.crypto.rsa import (
    create_new_key_pair,
)
from libp2p.peer.id import (
    ID,
)

ALPHABETS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def test_peer_id_multibase_encode_decode():
    peer_id = ID(b"\x12\x34\x56")
    multibase_str = peer_id.to_multibase("base58btc")
    assert multibase_str.startswith("z")
    decoded = ID.from_multibase(multibase_str)
    assert decoded == peer_id


def test_backward_compatibility():
    # Old base58 strings should still work
    old_format = base58.b58encode(b"\x12\x34\x56").decode()
    peer_id = ID.from_string(old_format)
    assert peer_id.to_bytes() == b"\x12\x34\x56"


def test_from_string_legacy_qm_prefix():
    mh_bytes = multihash.digest(b"test-key", "sha2-256").encode()
    pid = ID(mh_bytes)
    b58 = pid.to_base58()
    assert b58.startswith("Qm")
    assert ID.from_string(b58) == pid


def test_from_string_legacy_1_prefix():
    mh_bytes = multihash.digest(b"key", 0x00).encode()
    pid = ID(mh_bytes)
    b58 = pid.to_base58()
    assert b58.startswith("1")
    assert ID.from_string(b58) == pid


def test_from_string_multibase_base32():
    mh_bytes = multihash.digest(b"some-key", "sha2-256").encode()
    pid = ID(mh_bytes)
    mb32 = pid.to_multibase("base32")
    assert ID.from_string(mb32) == pid


def test_from_string_ambiguous_prefers_base58():
    result = ID.from_string("f123abc")
    expected = ID.from_base58("f123abc")
    assert result == expected


def test_encoding_detection():
    peer_id = ID(b"\x12\x34\x56")
    multibase_str = peer_id.to_multibase("base64")
    assert multibase_str.startswith("m")
    encoding = multibase.get_codec(multibase_str).encoding
    assert encoding == "base64"


def test_invalid_multibase():
    with pytest.raises(multibase.InvalidMultibaseStringError):
        ID.from_multibase("invalid")


def test_multiple_encodings():
    peer_id = ID(b"\x12\x34\x56")
    base58btc = peer_id.to_multibase("base58btc")
    base64 = peer_id.to_multibase("base64")
    base32 = peer_id.to_multibase("base32")
    assert ID.from_multibase(base58btc) == peer_id
    assert ID.from_multibase(base64) == peer_id
    assert ID.from_multibase(base32) == peer_id


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
    algo = multihash.Func.sha2_256
    mh_digest = multihash.digest(key_bin, algo)
    expected = ID(mh_digest.encode())

    actual = ID.from_pubkey(public_key)

    assert actual == expected
