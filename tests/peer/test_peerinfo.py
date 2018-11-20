from peer.peerinfo import info_from_p2p_addr
import multiaddr


def test_info_from_p2p_addr():
    m = multiaddr.Multiaddr('/ip4/127.0.0.1/tcp/8000/ipfs/3YgLAeMKSAPcGqZkAt8mREqhQXmJT8SN8VCMN4T6ih4GNX9wvK8mWJnWZ1qA2mLdCQ')
    info = info_from_p2p_addr(m)
    assert info.peer_id.pretty() == '3YgLAeMKSAPcGqZkAt8mREqhQXmJT8SN8VCMN4T6ih4GNX9wvK8mWJnWZ1qA2mLdCQ'
    assert len(info.addrs) == 1
    assert str(info.addrs[0]) == '/ip4/127.0.0.1/tcp/8000'
