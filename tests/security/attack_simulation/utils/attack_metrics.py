class AttackMetricsUtils:
    """Utility functions for metrics"""

    @staticmethod
    def success_rate_ratio(successful: int, total: int) -> float:
        return successful / total if total > 0 else 0.0
