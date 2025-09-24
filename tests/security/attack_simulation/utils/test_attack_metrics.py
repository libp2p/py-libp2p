from .attack_metrics import AttackMetricsUtils


def test_success_rate_ratio():
    assert AttackMetricsUtils.success_rate_ratio(5, 10) == 0.5
    assert AttackMetricsUtils.success_rate_ratio(0, 0) == 0.0
