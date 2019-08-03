import random
import multihash
import pytest
import base58
from Crypto.PublicKey import RSA
from libp2p.peer.id import ID


ALPHABETS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def test_init():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    peer_id = ID(random_id_string.encode())
    assert peer_id == random_id_string.encode()


def test_no_init_value():
    with pytest.raises(Exception) as _:
        ID()


def test_pretty():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    peer_id = ID(random_id_string.encode())
    actual = peer_id.pretty()
    expected = base58.b58encode(random_id_string).decode()

    assert actual == expected


def test_str_less_than_10():
    random_id_string = ""
    for _ in range(5):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    peer_id = base58.b58encode(random_id_string).decode()
    expected = peer_id
    actual = ID(random_id_string.encode()).__str__()

    assert actual == expected


def test_str_more_than_10():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    peer_id = base58.b58encode(random_id_string).decode()
    expected = peer_id
    actual = ID(random_id_string.encode()).__str__()

    assert actual == expected


def test_eq_true():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    peer_id = ID(random_id_string.encode())

    assert peer_id == base58.b58encode(random_id_string).decode()
    assert peer_id == random_id_string.encode()
    assert peer_id == ID(random_id_string.encode())


def test_eq_false():
    peer_id = ID("efgh")
    other = ID("abcd")

    assert peer_id != other


def test_hash():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)

    expected = hash(random_id_string.encode())
    actual = ID(random_id_string.encode()).__hash__()

    assert actual == expected


def test_id_to_base58():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    expected = base58.b58encode(random_id_string).decode()
    actual = ID(random_id_string.encode()).to_base58()

    assert actual == expected


def test_id_from_base58():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    expected = ID(base58.b58decode(random_id_string))
    actual = ID.from_base58(random_id_string.encode())

    assert actual == expected


def test_id_from_public_key():
    bits_list = [1024, 1280, 1536, 1536, 2048]
    key = RSA.generate(random.choice(bits_list))
    key_bin = key.exportKey("DER")
    algo = multihash.Func.sha2_256
    mh_digest = multihash.digest(key_bin, algo)
    expected = ID(mh_digest.encode())
    actual = ID.from_pubkey(key_bin)

    assert actual == expected
