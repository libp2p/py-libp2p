from libp2p.crypto.ecc import (
    ECCPublicKey,
    create_new_key_pair,
)


def test_ecc_public_key_round_trip() -> None:
    key_pair = create_new_key_pair("P-256")
    public_key = key_pair.public_key

    pub_bytes = public_key.to_bytes()
    assert isinstance(pub_bytes, bytes)
    assert len(pub_bytes) > 0

    decoded = ECCPublicKey.from_bytes(pub_bytes, "P-256")
    assert decoded.to_bytes() == pub_bytes


def test_ecc_private_key_to_bytes() -> None:
    key_pair = create_new_key_pair("P-256")
    priv_bytes = key_pair.private_key.to_bytes()
    assert isinstance(priv_bytes, bytes)
    assert b"BEGIN EC PRIVATE KEY" in priv_bytes
