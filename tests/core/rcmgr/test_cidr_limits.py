from libp2p.rcmgr.cidr_limits import CIDRLimiter


class TestCIDRLimiter:
    def test_allow_without_rules(self) -> None:
        limiter = CIDRLimiter()
        assert limiter.allow("10.0.0.1") is True

    def test_allow_with_non_matching_ip(self) -> None:
        limiter = CIDRLimiter(rules=[("10.0.0.0/24", 1)])
        assert limiter.allow("192.168.1.10") is True

    def test_acquire_and_deny_on_limit(self) -> None:
        limiter = CIDRLimiter(rules=[("10.0.0.0/24", 1)])
        # First acquire should succeed
        assert limiter.acquire("10.0.0.1") is True
        # Second concurrent acquire for same subnet should fail
        assert limiter.acquire("10.0.0.42") is False

    def test_release_allows_future_acquire(self) -> None:
        limiter = CIDRLimiter(rules=[("10.0.0.0/24", 1)])
        assert limiter.acquire("10.0.0.2") is True
        limiter.release("10.0.0.2")
        assert limiter.acquire("10.0.0.200") is True
