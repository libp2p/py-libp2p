from libp2p.transport.upgrader import TransportUpgrader

def test_upgrade_security():
    t = TransportUpgrader(None, None)
    t.upgrade_security()
