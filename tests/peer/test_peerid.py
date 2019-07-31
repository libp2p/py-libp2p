import random
import multihash
import pytest
import base58
from Crypto.PublicKey import RSA
from libp2p.peer.id import (
    ID,
    id_b58_encode,
)


ALPHABETS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def test_init():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    peer_id = ID(random_id_string.encode())
    #pylint: disable=protected-access
    assert peer_id == random_id_string.encode()



def test_no_init_value():
    with pytest.raises(Exception) as _:
        # pylint: disable=no-value-for-parameter
        ID()


def test_pretty():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    peer_id = ID(random_id_string.encode())
    actual = peer_id.pretty()
    expected = base58.b58encode(random_id_string.encode()).decode()

    assert actual == expected


def test_str_less_than_10():
    random_id_string = ""
    for _ in range(5):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    peer_id = base58.b58encode(random_id_string.encode()).decode()
    expected = peer_id
    actual = ID(random_id_string.encode()).__str__()

    assert actual == expected


def test_str_more_than_10():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    peer_id = base58.b58encode(random_id_string.encode()).decode()
    expected = peer_id
    actual = ID(random_id_string.encode()).__str__()

    assert actual == expected


def test_eq_true():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    peer_id = ID(random_id_string.encode())

    assert peer_id == ID(random_id_string.encode())
    assert peer_id.to_bytes() == random_id_string.encode()


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


def test_id_b58_encode():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    expected = base58.b58encode(random_id_string.encode()).decode()
    actual = id_b58_encode(ID(random_id_string.encode()))

    assert actual == expected


def test_id_b58_decode():
    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    expected = ID(base58.b58decode(random_id_string.encode()))
    actual = ID.from_base58(random_id_string.encode())

    assert actual == expected


def test_id_from_public_key():
    bits_list = [1024, 1280, 1536, 1536, 2048]
    key = RSA.generate(random.choice(bits_list))
    key_bin = key.exportKey("DER")
    algo = multihash.Func.sha2_256
    mh_digest = multihash.digest(key_bin, algo)
    expected = ID(mh_digest.encode())
    actual = ID.from_pubkey(key)

    assert actual == expected


def test_id_from_private_key():
    key = RSA.generate(2048, e=65537)
    id_from_pub = ID.from_pubkey(key.publickey())
    id_from_priv = ID.from_privkey(key)
    assert id_from_pub == id_from_priv
