from collections.abc import Sequence

import pytest
from multiaddr import Multiaddr

from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.peer.id import ID
from libp2p.peer.peerdata import (
    PeerData,
    PeerDataError,
)
from libp2p.peer.peerstore import PeerStore

MOCK_ADDR = Multiaddr("/ip4/127.0.0.1/tcp/4001")
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
    protocols: Sequence[str] = ["protocol1", "protocol2"]
    peer_data.add_protocols(protocols)
    assert peer_data.get_protocols() == protocols


# Test case when setting protocols
def test_set_protocols():
    peer_data = PeerData()
    protocols: Sequence[str] = ["protocol1", "protocol2"]
    peer_data.set_protocols(protocols)
    assert peer_data.get_protocols() == protocols


# Test case when removing protocols:
def test_remove_protocols():
    peer_data = PeerData()
    protocols: Sequence[str] = ["protocol1", "protocol2"]
    peer_data.set_protocols(protocols)

    peer_data.remove_protocols(["protocol1"])
    assert peer_data.get_protocols() == ["protocol2"]


# Test case when clearing the protocol list:
def test_clear_protocol_data():
    peer_data = PeerData()
    protocols: Sequence[str] = ["protocol1", "protocol2"]
    peer_data.set_protocols(protocols)

    peer_data.clear_protocol_data()
    assert peer_data.get_protocols() == []


# Test case when supports protocols:
def test_supports_protocols():
    peer_data = PeerData()
    peer_data.set_protocols(["protocol1", "protocol2", "protocol3"])

    input_protocols = ["protocol1", "protocol4", "protocol2"]
    supported = peer_data.supports_protocols(input_protocols)

    assert supported == ["protocol1", "protocol2"]


# Test case for first supported protocol is found
def test_first_supported_protocol_found():
    peer_data = PeerData()
    peer_data.set_protocols(["protocolA", "protocolB"])

    input_protocols = ["protocolC", "protocolB", "protocolA"]
    first = peer_data.first_supported_protocol(input_protocols)

    assert first == "protocolB"


# Test case for first supported protocol not found
def test_first_supported_protocol_none():
    peer_data = PeerData()
    peer_data.set_protocols(["protocolX", "protocolY"])

    input_protocols = ["protocolA", "protocolB"]
    first = peer_data.first_supported_protocol(input_protocols)

    assert first == "None supported"


# Test case when adding addresses
def test_add_addrs():
    peer_data = PeerData()
    addresses: Sequence[Multiaddr] = [MOCK_ADDR]
    peer_data.add_addrs(addresses)
    assert peer_data.get_addrs() == addresses


# Test case when adding same address more than once
def test_add_dup_addrs():
    peer_data = PeerData()
    addresses: Sequence[Multiaddr] = [MOCK_ADDR, MOCK_ADDR]
    peer_data.add_addrs(addresses)
    peer_data.add_addrs(addresses)
    assert peer_data.get_addrs() == [MOCK_ADDR]


# Test case for clearing addresses
def test_clear_addrs():
    peer_data = PeerData()
    addresses: Sequence[Multiaddr] = [MOCK_ADDR]
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


# Test case for clearing metadata
def test_clear_metadata():
    peer_data = PeerData()
    peer_data.metadata = {"key1": "value1", "key2": "value2"}

    peer_data.clear_metadata()
    assert peer_data.metadata == {}


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


# Test case for returning all the peers with stored keys
def test_peer_with_keys():
    peer_store = PeerStore()
    peer_id_1 = ID(b"peer1")
    peer_id_2 = ID(b"peer2")

    peer_data_1 = PeerData()
    peer_data_2 = PeerData()

    peer_data_1.pubkey = MOCK_PUBKEY
    peer_data_2.pubkey = None

    peer_store.peer_data_map = {
        peer_id_1: peer_data_1,
        peer_id_2: peer_data_2,
    }

    assert peer_store.peer_with_keys() == [peer_id_1]


# Test case for clearing the key book
def test_clear_keydata():
    peer_store = PeerStore()
    peer_id = ID(b"peer123")
    peer_data = PeerData()

    peer_data.pubkey = MOCK_PUBKEY
    peer_data.privkey = MOCK_PRIVKEY
    peer_store.peer_data_map = {peer_id: peer_data}

    peer_store.clear_keydata(peer_id)

    assert peer_data.pubkey is None
    assert peer_data.privkey is None


# Test case for recording latency for the first time
def test_record_latency_initial():
    peer_data = PeerData()
    assert peer_data.latency_EWMA() == 0

    peer_data.record_latency(100.0)
    assert peer_data.latency_EWMA() == 100.0


# Test case for updating latency
def test_record_latency_updates_ewma():
    peer_data = PeerData()
    peer_data.record_latency(100.0)  # first measurement
    first = peer_data.latency_EWMA()

    peer_data.record_latency(50.0)  # second measurement
    second = peer_data.latency_EWMA()

    assert second < first  # EWMA should have smoothed downward
    assert second > 50.0  # Not as low as the new latency
    assert second != first


def test_clear_metrics():
    peer_data = PeerData()
    peer_data.record_latency(200.0)
    assert peer_data.latency_EWMA() == 200.0

    peer_data.clear_metrics()
    assert peer_data.latency_EWMA() == 0
