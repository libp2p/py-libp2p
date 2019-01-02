import random
import string
import multihash
import pytest
import base58
from Crypto.PublicKey import RSA
from peer.id import ID, id_b58_encode, id_b58_decode, id_from_public_key, id_from_private_key

ALPHABETS = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def test_init_():
    random_id_string = ''
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    peer_id = ID(random_id_string)
    assert peer_id._id_str == random_id_string

def test_no_init_value():
    with pytest.raises(Exception) as e_info:
        peer_id = ID()

def test_pretty():
    random_id_string = ''
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    peer_id = ID(random_id_string)

    actual = peer_id.pretty()
    expected = base58.b58encode(random_id_string).decode()

    assert actual == expected

def test_str_less_than_10():
    random_id_string = ''
    for _ in range(5):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    pid = base58.b58encode(random_id_string).decode() 

    expected = "<peer.ID " + pid  + ">"
    actual = ID(random_id_string).__str__()

    assert actual == expected

def test_str_more_than_10():
    random_id_string = ''
    for _ in range(10):
         random_id_string += random.SystemRandom().choice(ALPHABETS)
    pid = base58.b58encode(random_id_string).decode()
    part_1, part_2 = pid[:2], pid[len(pid)-6:]

    expected = "<peer.ID " + part_1 + "*" + part_2 + ">"
    actual = ID(random_id_string).__str__()

    assert actual == expected

def test_eq_true():
    random_id_string = ''
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    other = ID(random_id_string)

    expected = True
    actual = ID(random_id_string).__eq__(other)

    assert actual == expected

def test_eq_false():
   other = ID("efgh")

   expected = False
   actual = ID("abcd").__eq__(other)

   assert actual == expected

def test_hash():
    random_id_string = ''
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)

    expected = hash(random_id_string)
    actual = ID(random_id_string).__hash__()

    assert actual == expected

def test_id_b58_encode():
    random_id_string = ''
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)

    expected = base58.b58encode(random_id_string).decode()
    actual = id_b58_encode(ID(random_id_string))

    assert actual == expected

def test_id_b58_decode():
    random_id_string = ''
    for _ in range(10):
         random_id_string += random.SystemRandom().choice(ALPHABETS)

    expected = ID(base58.b58decode(random_id_string))
    actual = id_b58_decode(random_id_string)

    assert actual == expected   

def test_id_from_public_key():
    bits_list = [1024, 1280, 1536, 1536, 2048]
    key = RSA.generate(random.choice(bits_list))
    key_bin = key.exportKey("DER")
    algo = multihash.Func.sha2_256
    mh_digest = multihash.digest(key_bin, algo)

    expected = ID(mh_digest.encode())
    actual = id_from_public_key(key)

    assert actual == expected

def test_id_from_private_key():
    key = RSA.generate(2048, e=65537)
    id_from_pub = id_from_public_key(key.publickey())
    id_from_priv = id_from_private_key(key)
    assert id_from_pub == id_from_priv

