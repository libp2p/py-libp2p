from libp2p.rcmgr.manager import ResourceManager


class TestPreUpgradeAdmission:
    def test_outbound_preupgrade_denied_by_cidr(self) -> None:
        # Deny any outbound to 127.0.0.0/8
        rm = ResourceManager(cidr_limits=[("127.0.0.0/8", 0)])
        scope = rm.open_connection(None, endpoint_ip="127.0.0.1")
        assert scope is None

    def test_outbound_preupgrade_allowed_by_cidr(self) -> None:
        # Allow exactly 1 outbound to 127.0.0.0/8
        rm = ResourceManager(cidr_limits=[("127.0.0.0/8", 1)])
        scope = rm.open_connection(None, endpoint_ip="127.0.0.1")
        assert scope is not None
        # Release and ensure subsequent acquire succeeds again
        scope.close()
        scope2 = rm.open_connection(None, endpoint_ip="127.0.0.1")
        assert scope2 is not None
        scope2.close()
