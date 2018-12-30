from Crypto.PublicKey import RSA
from peer.id import *
import multihash
import random
import string
import pytest
import base58

def test_init_():
	random_id_string = ''.join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(10))
	peer_id = ID(random_id_string)

	assert peer_id._id_str == random_id_string

def test_no_init_value():
	with pytest.raises(Exception) as e_info:
		peer_if = ID()

def test_pretty():
	random_id_string = ''.join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(10))
	peer_id = ID(random_id_string)

	actual = peer_id.pretty()
	expected = base58.b58encode(random_id_string).decode()

	assert actual == expected

def test_str_less_than_10():
	random_id_string = ''.join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(5))
	pid = base58.b58encode(random_id_string).decode() 

	expected = "<peer.ID " + pid  + ">"
	actual =  ID(random_id_string).__str__()

	assert actual == expected

def test_str_more_than_10():
	random_id_string = ''.join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(10))
	pid = base58.b58encode(random_id_string).decode()
	part_1, part_2 = pid[:2], pid[len(pid)-6:]

	expected = "<peer.ID " + part_1 + "*" + part_2 + ">"
	actual =  ID(random_id_string).__str__()

	assert actual == expected

def test_eq_true():
	random_id_string = ''.join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(10))	
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
	random_id_string = ''.join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(10))

	expected = hash(random_id_string)
	actual = ID(random_id_string).__hash__()

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

