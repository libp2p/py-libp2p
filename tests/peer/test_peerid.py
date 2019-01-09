from Crypto.PublicKey import RSA

from libp2p.peer.id import id_from_private_key, id_from_public_key


def test_id_from_private_key():
    key = RSA.generate(2048, e=65537)
    id_from_pub = id_from_public_key(key.publickey())
    id_from_priv = id_from_private_key(key)
    assert id_from_pub == id_from_priv
