import multiaddr
import random
import string
import pytest
from peer.peerinfo import *
from peer.peerdata import PeerData
from peer.id import *

def test_init_():
	peer_data = PeerData()
	random_addrs = [random.randint(0, 255) for r in range(4)]
	peer_data.add_addrs(random_addrs)
	random_id_string = ''.join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(10))
	peer_id = ID(random_id_string)

	peer_info = PeerInfo(peer_id, peer_data)

	assert peer_info.peer_id == peer_id
	assert peer_info.addrs == random_addrs

def test_init_no_value():
	with pytest.raises(Exception) as e_info:
		peer_info = PeerInfo()	

def test_invalid_addr_1():
	with pytest.raises(InvalidAddrError):
		actual = info_from_p2p_addr(None)

def test_invalid_addr_2(monkeypatch):
	random_addrs = [random.randint(0, 255) for r in range(4)]
	monkeypatch.setattr("multiaddr.util.split", lambda x: None)
	with pytest.raises(InvalidAddrError):
		actual = info_from_p2p_addr(random_addrs)


def test_info_from_p2p_addr():
    # pylint: disable=line-too-long
    m_addr = multiaddr.Multiaddr('/ip4/127.0.0.1/tcp/8000/ipfs/3YgLAeMKSAPcGqZkAt8mREqhQXmJT8SN8VCMN4T6ih4GNX9wvK8mWJnWZ1qA2mLdCQ')
    info = info_from_p2p_addr(m_addr)
    assert info.peer_id.pretty() == '3YgLAeMKSAPcGqZkAt8mREqhQXmJT8SN8VCMN4T6ih4GNX9wvK8mWJnWZ1qA2mLdCQ'
    assert len(info.addrs) == 1
    assert str(info.addrs[0]) == '/ip4/127.0.0.1/tcp/8000'
