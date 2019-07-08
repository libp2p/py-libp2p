import random
import multiaddr
import pytest
from libp2p.peer.peerinfo import PeerInfo, info_from_p2p_addr, InvalidAddrError
from libp2p.peer.peerdata import PeerData
from libp2p.peer.id import ID

ALPHABETS = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def test_init_():
    peer_data = PeerData()
    random_addrs = [random.randint(0, 255) for r in range(4)]
    peer_data.add_addrs(random_addrs)
    random_id_string = ''
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)
    peer_id = ID(random_id_string)
    peer_info = PeerInfo(peer_id, peer_data)

    assert peer_info.peer_id == peer_id
    assert peer_info.addrs == random_addrs

def test_init_no_value():
    with pytest.raises(Exception) as _:
        # pylint: disable=no-value-for-parameter
        PeerInfo()

def test_invalid_addr_1():
    with pytest.raises(InvalidAddrError):
        info_from_p2p_addr(None)

def test_invalid_addr_2(monkeypatch):
    random_addr = random.randint(0, 255)
    monkeypatch.setattr("multiaddr.Multiaddr.split", lambda x: None)
    with pytest.raises(InvalidAddrError):
        info_from_p2p_addr(random_addr)

def test_info_from_p2p_addr():
    # pylint: disable=line-too-long
    m_addr = multiaddr.Multiaddr('/ip4/127.0.0.1/tcp/8000/p2p/3YgLAeMKSAPcGqZkAt8mREqhQXmJT8SN8VCMN4T6ih4GNX9wvK8mWJnWZ1qA2mLdCQ')
    info = info_from_p2p_addr(m_addr)
    assert info.peer_id.pretty() == '3YgLAeMKSAPcGqZkAt8mREqhQXmJT8SN8VCMN4T6ih4GNX9wvK8mWJnWZ1qA2mLdCQ'
    assert len(info.addrs) == 1
    assert str(info.addrs[0]) == '/ip4/127.0.0.1/tcp/8000'
