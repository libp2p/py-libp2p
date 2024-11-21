import pytest

from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.peer.peerdata import (
    PeerData,
    PeerDataError,
)

MOCK_ADDR = "/peer"
MOCK_KEYPAIR = create_new_key_pair()
MOCK_PUBKEY = MOCK_KEYPAIR.public_key
MOCK_PRIVKEY = MOCK_KEYPAIR.private_key


# Test case when no protocols have been added
def test_get_protocols_empty():
    peer_data = PeerData()
    assert peer_data.get_protocols() == []


# Test case when adding protocols
def test_add_protocols():
    peer_data = PeerData()
    protocols = ["protocol1", "protocol2"]
    peer_data.add_protocols(protocols)
    assert peer_data.get_protocols() == protocols


# Test case when setting protocols
def test_set_protocols():
    peer_data = PeerData()
    protocols = ["protocolA", "protocolB"]
    peer_data.set_protocols(protocols)
    assert peer_data.get_protocols() == protocols


# Test case when adding addresses
def test_add_addrs():
    peer_data = PeerData()
    addresses = [MOCK_ADDR]
    peer_data.add_addrs(addresses)
    assert peer_data.get_addrs() == addresses


# Test case when adding same address more than once
def test_add_dup_addrs():
    peer_data = PeerData()
    addresses = [MOCK_ADDR, MOCK_ADDR]
    peer_data.add_addrs(addresses)
    peer_data.add_addrs(addresses)
    assert peer_data.get_addrs() == [MOCK_ADDR]


# Test case for clearing addresses
def test_clear_addrs():
    peer_data = PeerData()
    addresses = [MOCK_ADDR]
    peer_data.add_addrs(addresses)
    peer_data.clear_addrs()
    assert peer_data.get_addrs() == []


# Test case for adding metadata
def test_put_metadata():
    peer_data = PeerData()
    key = "key1"
    value = "value1"
    peer_data.put_metadata(key, value)
    assert peer_data.get_metadata(key) == value


# Test case for key not found in metadata
def test_get_metadata_key_not_found():
    peer_data = PeerData()
    with pytest.raises(PeerDataError):
        peer_data.get_metadata("nonexistent_key")


# Test case for adding public key
def test_add_pubkey():
    peer_data = PeerData()
    peer_data.add_pubkey(MOCK_PUBKEY)
    assert peer_data.get_pubkey() == MOCK_PUBKEY


# Test case when public key is not set
def test_get_pubkey_not_found():
    peer_data = PeerData()
    with pytest.raises(PeerDataError):
        peer_data.get_pubkey()


# Test case for adding private key
def test_add_privkey():
    peer_data = PeerData()
    peer_data.add_privkey(MOCK_PRIVKEY)
    assert peer_data.get_privkey() == MOCK_PRIVKEY


# Test case when private key is not set
def test_get_privkey_not_found():
    peer_data = PeerData()
    with pytest.raises(PeerDataError):
        peer_data.get_privkey()
