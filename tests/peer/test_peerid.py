import pytest

from Crypto.PublicKey import RSA
from peer import id


def test_id_from_private_key():
    key = RSA.generate(2048, e=65537)
    id_from_pub = id.id_from_public_key(key.publickey())
    id_from_priv = id.id_from_private_key(key)
    assert id_from_pub._id_str == id_from_priv._id_str
