import pytest
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

from libp2p.crypto.secp256k1 import (
    SECP256K1_ORDER,
    Secp256k1PrivateKey,
    Secp256k1PublicKey,
    create_new_key_pair,
)
from libp2p.crypto.serialization import (
    deserialize_private_key,
    deserialize_public_key,
)

# A key and signatures produced by libsecp256k1, which signs with RFC 6979
# nonces and returns the low-S form.
SECRET = bytes.fromhex(
    "d759f4853167b24b314bc59215ad037ce429f2f59071d5f97f09bf9aef66c3b2"
)
PUBLIC_KEY = bytes.fromhex(
    "025fafe0bf1de50426d847dc6e984d0a844680260838da25117d596ce570004dbe"
)
PUBLIC_KEY_UNCOMPRESSED = bytes.fromhex(
    "045fafe0bf1de50426d847dc6e984d0a844680260838da25117d596ce570004dbe"
    "2281dea455282fbd2088732cd7bd440febe43e5533310c8db7fdfc79f7d3ce52"
)
SIGNATURES = [
    (
        b"",
        "304402204e5c04efee0f9bdd7d8c27650d9594f0ecc0b0712e932ccdf020c778f268480a"
        "022023522aaa98c0981292528f9b2469c5b3db3f8ab860c4d01bb659c397767e00f7",
    ),
    (
        b"hello",
        "30440220393d978540ae84692b0d07de1f053a8340d32d7634548e8fa379435fc33161cb"
        "02206b05b9703afdca697714b5bd9f29f25e5d96137e681f1816d04f17ec6d0dd9d6",
    ),
    (
        b"libp2p",
        "304502210080f1646971d5b9b1e170fd0eaa1b2207cc10e86b58d60cae7da19a366d86fb"
        "52022051855a6d921b37a0a223a1621f4f8de49266ee4d69d8e3557eac1fea5c861333",
    ),
]


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


def test_key_from_secret():
    key_pair = create_new_key_pair(SECRET)

    assert key_pair.private_key.to_bytes() == SECRET
    assert key_pair.public_key.to_bytes() == PUBLIC_KEY


def test_short_secret_is_padded():
    key_pair = create_new_key_pair(b"\x01")

    assert key_pair.private_key.to_bytes() == bytes(31) + b"\x01"


@pytest.mark.parametrize("secret", [bytes(32), SECP256K1_ORDER.to_bytes(32, "big")])
def test_secret_out_of_range(secret):
    with pytest.raises(ValueError):
        create_new_key_pair(secret)


def test_public_key_from_uncompressed_bytes():
    public_key = Secp256k1PublicKey.from_bytes(PUBLIC_KEY_UNCOMPRESSED)

    assert public_key.to_bytes() == PUBLIC_KEY


@pytest.mark.parametrize("data, signature", SIGNATURES)
def test_sign_matches_libsecp256k1(data, signature):
    private_key = Secp256k1PrivateKey.from_bytes(SECRET)

    assert private_key.sign(data).hex() == signature


@pytest.mark.parametrize("data, signature", SIGNATURES)
def test_verify_libsecp256k1_signature(data, signature):
    public_key = Secp256k1PublicKey.from_bytes(PUBLIC_KEY)

    assert public_key.verify(data, bytes.fromhex(signature))
    assert not public_key.verify(data + b"!", bytes.fromhex(signature))


def test_sign_returns_low_s():
    private_key = create_new_key_pair().private_key

    for i in range(32):
        _, s = decode_dss_signature(private_key.sign(bytes([i])))
        assert s <= SECP256K1_ORDER // 2


def test_verify_rejects_high_s():
    data, signature = SIGNATURES[0]
    r, s = decode_dss_signature(bytes.fromhex(signature))
    high_s_signature = encode_dss_signature(r, SECP256K1_ORDER - s)
    public_key = Secp256k1PublicKey.from_bytes(PUBLIC_KEY)

    assert not public_key.verify(data, high_s_signature)


@pytest.mark.parametrize(
    "signature", [b"", b"\x30\x00", bytes.fromhex(SIGNATURES[0][1]) + b"\x00"]
)
def test_verify_rejects_malformed_signature(signature):
    public_key = Secp256k1PublicKey.from_bytes(PUBLIC_KEY)

    assert not public_key.verify(SIGNATURES[0][0], signature)
