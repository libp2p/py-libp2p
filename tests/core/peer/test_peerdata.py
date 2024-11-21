import unittest
from unittest.mock import (
    MagicMock,
)

from multiaddr import (
    Multiaddr,
)

from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)
from libp2p.peer.peerdata import (
    PeerData,
    PeerDataError,
)


class TestPeerData(unittest.TestCase):
    def setUp(self):
        # This will run before each test method
        self.peer_data = PeerData()
        self.mock_pubkey = MagicMock(PublicKey)
        self.mock_privkey = MagicMock(PrivateKey)
        self.mock_addr = MagicMock(Multiaddr)

    def test_get_protocols_empty(self):
        # Test case when no protocols have been added
        self.assertEqual(self.peer_data.get_protocols(), [])

    def test_add_protocols(self):
        # Test case when adding protocols
        protocols = ["protocol1", "protocol2"]
        self.peer_data.add_protocols(protocols)
        self.assertEqual(self.peer_data.get_protocols(), protocols)

    def test_set_protocols(self):
        # Test case when setting protocols
        protocols = ["protocolA", "protocolB"]
        self.peer_data.set_protocols(protocols)
        self.assertEqual(self.peer_data.get_protocols(), protocols)

    def test_add_addrs(self):
        # Test case when adding addresses
        addresses = [self.mock_addr]
        self.peer_data.add_addrs(addresses)
        self.assertEqual(self.peer_data.get_addrs(), addresses)

    def test_add_dup_addrs(self):
        # Test case when adding same address more than once
        addresses = [self.mock_addr, self.mock_addr]
        self.peer_data.add_addrs(addresses)
        self.peer_data.add_addrs(addresses)
        self.assertEqual(self.peer_data.get_addrs(), [self.mock_addr])

    def test_clear_addrs(self):
        # Test case for clearing addresses
        addresses = [self.mock_addr]
        self.peer_data.add_addrs(addresses)
        self.peer_data.clear_addrs()
        self.assertEqual(self.peer_data.get_addrs(), [])

    def test_put_metadata(self):
        # Test case for adding metadata
        key = "key1"
        value = "value1"
        self.peer_data.put_metadata(key, value)
        self.assertEqual(self.peer_data.get_metadata(key), value)

    def test_get_metadata_key_not_found(self):
        # Test case for key not found in metadata
        with self.assertRaises(PeerDataError):
            self.peer_data.get_metadata("nonexistent_key")

    def test_add_pubkey(self):
        # Test case for adding public key
        self.peer_data.add_pubkey(self.mock_pubkey)
        self.assertEqual(self.peer_data.get_pubkey(), self.mock_pubkey)

    def test_get_pubkey_not_found(self):
        # Test case when public key is not set
        with self.assertRaises(PeerDataError):
            self.peer_data.get_pubkey()

    def test_add_privkey(self):
        # Test case for adding private key
        self.peer_data.add_privkey(self.mock_privkey)
        self.assertEqual(self.peer_data.get_privkey(), self.mock_privkey)

    def test_get_privkey_not_found(self):
        # Test case when private key is not set
        with self.assertRaises(PeerDataError):
            self.peer_data.get_privkey()
