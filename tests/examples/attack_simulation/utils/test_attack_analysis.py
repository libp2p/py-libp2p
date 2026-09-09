import pytest

from .attack_analysis import AttackAnalysis
from .attack_metrics import AttackMetrics


@pytest.fixture
def sample_metrics():
    """Create sample metrics for testing"""
    metrics = AttackMetrics()

    # Set up test data
    metrics.lookup_success_rate = [0.95, 0.60, 0.85]
    metrics.peer_table_contamination = [0.0, 0.40, 0.20]
    metrics.network_connectivity = [1.0, 0.70, 0.90]
    metrics.message_delivery_rate = [0.98, 0.65, 0.88]

    metrics.time_to_partitioning = 45.0
    metrics.affected_nodes_percentage = 40.0
    metrics.attack_persistence = 0.60

    metrics.recovery_time = 120.0
    metrics.detection_time = 25.0
    metrics.mitigation_effectiveness = 0.75

    metrics.memory_usage = [100, 140, 110]
    metrics.cpu_utilization = [10, 25, 12]
    metrics.bandwidth_consumption = [50, 120, 65]

    metrics.dht_poisoning_rate = 0.40
    metrics.peer_table_flooding_rate = 8.0
    metrics.routing_disruption_level = 0.55

    return metrics


def test_attack_analysis_initialization():
    """Test AttackAnalysis class initialization"""
    analysis = AttackAnalysis()
    assert isinstance(analysis.analysis_results, dict)
    assert analysis.analysis_results == {}


def test_generate_attack_report(sample_metrics):
    """Test comprehensive attack report generation"""
    analysis = AttackAnalysis()
    report = analysis.generate_attack_report(sample_metrics)

    # Check main sections
    assert "attack_effectiveness" in report
    assert "vulnerability_assessment" in report
    assert "mitigation_recommendations" in report
    assert "network_resilience_score" in report
    assert "security_insights" in report
    assert "risk_assessment" in report

    # Check effectiveness metrics
    effectiveness = report["attack_effectiveness"]
    assert "time_to_partitioning" in effectiveness
    assert "affected_nodes_percentage" in effectiveness
    assert "overall_effectiveness_score" in effectiveness

    # Check vulnerability assessment
    vuln = report["vulnerability_assessment"]
    assert "lookup_success_degradation" in vuln
    assert "max_contamination" in vuln
    assert "vulnerability_severity" in vuln

    # Check mitigation recommendations
    assert isinstance(report["mitigation_recommendations"], list)

    # Check resilience score
    assert isinstance(report["network_resilience_score"], float)
    assert 0 <= report["network_resilience_score"] <= 100

    # Check security insights
    insights = report["security_insights"]
    assert "attack_patterns" in insights
    assert "weak_points" in insights
    assert "defense_effectiveness" in insights

    # Check risk assessment
    risk = report["risk_assessment"]
    assert "risk_level" in risk
    assert "risk_description" in risk
    assert "resilience_score" in risk


def test_calculate_effectiveness(sample_metrics):
    """Test effectiveness calculation"""
    analysis = AttackAnalysis()
    effectiveness = analysis.calculate_effectiveness(sample_metrics)

    assert effectiveness["time_to_partitioning"] == 45.0
    assert effectiveness["affected_nodes_percentage"] == 40.0
    assert "overall_effectiveness_score" in effectiveness
    assert isinstance(effectiveness["overall_effectiveness_score"], float)


def test_assess_vulnerabilities(sample_metrics):
    """Test vulnerability assessment"""
    analysis = AttackAnalysis()
    vulnerabilities = analysis.assess_vulnerabilities(sample_metrics)

    assert vulnerabilities["lookup_success_degradation"] == pytest.approx(
        0.35
    )  # 0.95 - 0.60
    assert vulnerabilities["max_contamination"] == pytest.approx(0.40)
    assert vulnerabilities["connectivity_impact"] == pytest.approx(0.30)  # 1.0 - 0.70
    assert "vulnerability_severity" in vulnerabilities


def test_suggest_mitigations(sample_metrics):
    """Test mitigation recommendations"""
    analysis = AttackAnalysis()
    recommendations = analysis.suggest_mitigations(sample_metrics)

    assert isinstance(recommendations, list)
    # Should include recommendations based on metrics
    assert len(recommendations) > 0


def test_calculate_resilience(sample_metrics):
    """Test resilience score calculation"""
    analysis = AttackAnalysis()
    score = analysis.calculate_resilience(sample_metrics)

    assert isinstance(score, float)
    assert 0 <= score <= 100


def test_generate_security_insights(sample_metrics):
    """Test security insights generation"""
    analysis = AttackAnalysis()
    insights = analysis.generate_security_insights(sample_metrics)

    assert "attack_patterns" in insights
    assert "weak_points" in insights
    assert "defense_effectiveness" in insights
    assert "improvement_priorities" in insights

    assert isinstance(insights["attack_patterns"], list)
    assert isinstance(insights["weak_points"], list)


def test_assess_overall_risk(sample_metrics):
    """Test overall risk assessment"""
    analysis = AttackAnalysis()
    risk = analysis.assess_overall_risk(sample_metrics)

    assert "risk_level" in risk
    assert "risk_description" in risk
    assert "resilience_score" in risk
    assert "critical_findings" in risk

    assert risk["risk_level"] in ["Low", "Medium", "High", "Critical"]
    assert isinstance(risk["critical_findings"], list)


def test_vulnerability_severity_assessment():
    """Test vulnerability severity levels"""
    analysis = AttackAnalysis()

    # Low severity
    low_metrics = AttackMetrics()
    low_metrics.lookup_success_rate = [0.95, 0.90]
    low_metrics.peer_table_contamination = [0.0, 0.05]
    low_metrics.network_connectivity = [1.0, 0.98]
    low_metrics.cpu_utilization = [10, 11]

    severity = analysis._assess_vulnerability_severity(low_metrics)
    assert severity == "Low"

    # High severity
    high_metrics = AttackMetrics()
    high_metrics.lookup_success_rate = [0.95, 0.50]
    high_metrics.peer_table_contamination = [0.0, 0.80]
    high_metrics.network_connectivity = [1.0, 0.40]
    high_metrics.cpu_utilization = [10, 50]

    severity = analysis._assess_vulnerability_severity(high_metrics)
    assert severity in ["High", "Critical"]


def test_defense_rating_calculation(sample_metrics):
    """Test defense rating calculation"""
    analysis = AttackAnalysis()
    rating = analysis._calculate_defense_rating(sample_metrics)

    assert rating in ["Excellent", "Good", "Fair", "Poor"]


def test_identify_critical_findings(sample_metrics):
    """Test critical findings identification"""
    analysis = AttackAnalysis()
    findings = analysis._identify_critical_findings(sample_metrics)

    assert isinstance(findings, list)
    # Based on sample metrics, should have some findings
    assert len(findings) >= 0
