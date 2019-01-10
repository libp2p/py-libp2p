import multiaddr

from libp2p.peer.peerinfo import info_from_p2p_addr


def test_info_from_p2p_addr():
    # pylint: disable=line-too-long
    m_addr = multiaddr.Multiaddr('/ip4/127.0.0.1/tcp/8000/p2p/3YgLAeMKSAPcGqZkAt8mREqhQXmJT8SN8VCMN4T6ih4GNX9wvK8mWJnWZ1qA2mLdCQ')
    info = info_from_p2p_addr(m_addr)
    assert info.peer_id.pretty() == '3YgLAeMKSAPcGqZkAt8mREqhQXmJT8SN8VCMN4T6ih4GNX9wvK8mWJnWZ1qA2mLdCQ'
    assert len(info.addrs) == 1
    assert str(info.addrs[0]) == '/ip4/127.0.0.1/tcp/8000'
