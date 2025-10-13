import pytest

from libp2p.crypto.ed25519 import Ed25519PublicKey
from libp2p.crypto.pb import crypto_pb2
from libp2p.crypto.rsa import RSAPublicKey
from libp2p.crypto.secp256k1 import Secp256k1PublicKey
from libp2p.record.utils import split_key, unmarshal_public_key


def test_split_key_valid():
    ns, rest = split_key("ns/foo/bar")
    assert ns == "ns"
    assert rest == "foo/bar"


def test_split_key_single_slash():
    ns, rest = split_key("ns/foo")
    assert ns == "ns"
    assert rest == "foo"


def test_split_key_invalid():
    with pytest.raises(ValueError, match="invalid key format"):
        split_key("no_slash_key")


def make_serialized_pb_key(
        key_type: crypto_pb2.KeyType.ValueType,
        key_data: bytes
    ) -> bytes:
    """Helper to create a serialized PublicKey proto."""
    pb_key = crypto_pb2.PublicKey(key_type=key_type, data=key_data)
    return pb_key.SerializeToString()


def test_unmarshal_ed25519(monkeypatch):
    # Patch Ed25519PublicKey.from_bytes to ensure it's called
    called = {}
    def fake_from_bytes(data):
        called["ok"] = True
        return Ed25519PublicKey.__new__(Ed25519PublicKey)
    monkeypatch.setattr(Ed25519PublicKey, "from_bytes", staticmethod(fake_from_bytes))

    serialized = make_serialized_pb_key(crypto_pb2.KeyType.Ed25519, b"dummy_ed25519")
    key = unmarshal_public_key(serialized)
    assert isinstance(key, Ed25519PublicKey)
    assert called["ok"]


def test_unmarshal_rsa(monkeypatch):
    called = {}
    def fake_from_bytes(data):
        called["ok"] = True
        return RSAPublicKey.__new__(RSAPublicKey)
    monkeypatch.setattr(RSAPublicKey, "from_bytes", staticmethod(fake_from_bytes))

    serialized = make_serialized_pb_key(crypto_pb2.KeyType.RSA, b"dummy_rsa")
    key = unmarshal_public_key(serialized)
    assert isinstance(key, RSAPublicKey)
    assert called["ok"]


def test_unmarshal_secp256k1(monkeypatch):
    called = {}
    def fake_from_bytes(data):
        called["ok"] = True
        return Secp256k1PublicKey.__new__(Secp256k1PublicKey)
    monkeypatch.setattr(Secp256k1PublicKey, "from_bytes", staticmethod(fake_from_bytes))

    serialized = make_serialized_pb_key(crypto_pb2.KeyType.Secp256k1, b"dummy_secp")
    key = unmarshal_public_key(serialized)
    assert isinstance(key, Secp256k1PublicKey)
    assert called["ok"]


#def test_unmarshal_unsupported_key_type():
#    # fake key type
#    serialized = make_serialized_pb_key(999, b"whatever")
#    with pytest.raises(ValueError, match="Unsupported key type"):
#        unmarshal_public_key(serialized)
