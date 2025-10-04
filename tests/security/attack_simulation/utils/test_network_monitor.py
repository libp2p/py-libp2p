from .network_monitor import NetworkMonitor


def test_network_monitor():
    nm = NetworkMonitor()
    nm.set_peer_status("peer1", "online")
    nm.set_peer_status("peer2", "offline")
    online = nm.get_online_peers()
    assert online == ["peer1"]
