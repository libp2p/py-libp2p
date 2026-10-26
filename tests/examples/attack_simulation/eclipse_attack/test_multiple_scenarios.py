import json
import logging
import os
from pathlib import Path
import tempfile

import pytest

from ..config.attack_configs import ECLIPSE_ATTACK_CONFIGS
from .attack_scenarios import EclipseScenario
from .network_builder import AttackNetworkBuilder

logger = logging.getLogger(__name__)


def get_results_directory() -> Path:
    """Get results directory, defaulting to temp if TEST_TEMP_RESULTS is set"""
    if os.getenv("TEST_TEMP_RESULTS"):
        return Path(tempfile.gettempdir()) / "attack_simulation_results"
    else:
        return Path(__file__).parent.parent / "results"


@pytest.mark.trio
async def test_multiple_eclipse_scenarios():
    """Test multiple eclipse attack scenarios with different configurations"""
    builder = AttackNetworkBuilder()
    results = []

    for config in ECLIPSE_ATTACK_CONFIGS:
        logger.debug(f"Running scenario: {config['name']}")

        # Create network for this scenario
        honest, malicious = await builder.create_eclipse_test_network(
            int(config["honest_nodes"]),
            int(config["malicious_nodes"]),
            float(config["attack_intensity"]),
        )

        # Execute scenario
        scenario = EclipseScenario(honest, malicious)
        metrics = await scenario.execute()

        # Generate comprehensive report
        report = metrics.generate_attack_report()

        # Collect results
        result = {
            "scenario_name": config["name"],
            "config": config,
            "metrics": {
                "lookup_success_rate": metrics.lookup_success_rate,
                "peer_table_contamination": metrics.peer_table_contamination,
                "network_connectivity": metrics.network_connectivity,
                "message_delivery_rate": metrics.message_delivery_rate,
                "recovery_time": metrics.recovery_time,
                "time_to_partitioning": metrics.time_to_partitioning,
                "affected_nodes_percentage": metrics.affected_nodes_percentage,
                "attack_persistence": metrics.attack_persistence,
                "memory_usage": metrics.memory_usage,
                "cpu_utilization": metrics.cpu_utilization,
                "bandwidth_consumption": metrics.bandwidth_consumption,
                "dht_poisoning_rate": metrics.dht_poisoning_rate,
                "peer_table_flooding_rate": metrics.peer_table_flooding_rate,
                "routing_disruption_level": metrics.routing_disruption_level,
            },
            "analysis": report,
        }
        results.append(result)

        logger.debug(f"Results for {config['name']}:")
        logger.debug(f"  Lookup Success: {metrics.lookup_success_rate}")
        logger.debug(f"  Contamination: {max(metrics.peer_table_contamination):.1%}")
        logger.debug(f"  Affected Nodes: {metrics.affected_nodes_percentage:.1f}%")
        logger.debug(f"  Recovery Time: {metrics.recovery_time:.1f}s")
        resilience_score = report["network_resilience_score"]
        logger.debug(f"  Resilience Score: {resilience_score:.1f}/100")

    # Save detailed results to file
    results_dir = get_results_directory()
    results_file = results_dir / "comprehensive_attack_results.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)

    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    # Save summary report
    summary_file = results_dir / "attack_summary_report.json"
    summary = generate_attack_summary(results)

    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)

    logger.debug(f"Detailed results saved to: {results_file}")
    logger.debug(f"Summary report saved to: {summary_file}")

    # Basic assertions
    assert len(results) == len(ECLIPSE_ATTACK_CONFIGS)
    for result in results:
        assert "scenario_name" in result
        assert "analysis" in result
        assert isinstance(result["analysis"], dict)
        assert isinstance(
            result["analysis"].get("network_resilience_score"), (int, float)
        )


def generate_attack_summary(results: list) -> dict:
    """Generate a comprehensive summary of all attack scenarios"""
    summary = {
        "total_scenarios": len(results),
        "attack_effectiveness_analysis": {},
        "vulnerability_patterns": {},
        "mitigation_insights": {},
        "network_resilience_overview": {},
        "recommendations": [],
    }

    # Analyze attack effectiveness
    resilience_scores = [r["analysis"]["network_resilience_score"] for r in results]
    affected_percentages = [r["metrics"]["affected_nodes_percentage"] for r in results]
    recovery_times = [r["metrics"]["recovery_time"] for r in results]

    summary["attack_effectiveness_analysis"] = {
        "average_resilience_score": sum(resilience_scores) / len(resilience_scores),
        "min_resilience_score": min(resilience_scores),
        "max_resilience_score": max(resilience_scores),
        "average_affected_nodes": sum(affected_percentages) / len(affected_percentages),
        "average_recovery_time": sum(recovery_times) / len(recovery_times),
        "most_vulnerable_scenario": results[
            resilience_scores.index(min(resilience_scores))
        ]["scenario_name"],
        "most_resilient_scenario": results[
            resilience_scores.index(max(resilience_scores))
        ]["scenario_name"],
    }

    # Identify vulnerability patterns
    high_impact_scenarios = [
        r for r in results if r["analysis"]["network_resilience_score"] < 50
    ]
    summary["vulnerability_patterns"] = {
        "high_impact_scenarios": [s["scenario_name"] for s in high_impact_scenarios],
        "common_vulnerabilities": identify_common_vulnerabilities(results),
        "scale_impact": analyze_scale_impact(results),
    }

    # Collect mitigation recommendations
    all_recommendations = []
    for result in results:
        all_recommendations.extend(result["analysis"]["mitigation_recommendations"])

    # Remove duplicates and count frequency
    recommendation_counts = {}
    for rec in all_recommendations:
        recommendation_counts[rec] = recommendation_counts.get(rec, 0) + 1

    summary["mitigation_insights"] = {
        "top_recommendations": sorted(
            recommendation_counts.items(), key=lambda x: x[1], reverse=True
        )[:5],
        "unique_recommendations": len(set(all_recommendations)),
    }

    # Network resilience overview
    summary["network_resilience_overview"] = {
        "resilience_distribution": {
            "excellent": len([s for s in resilience_scores if s >= 80]),
            "good": len([s for s in resilience_scores if 60 <= s < 80]),
            "moderate": len([s for s in resilience_scores if 40 <= s < 60]),
            "poor": len([s for s in resilience_scores if s < 40]),
        },
        "correlation_analysis": analyze_correlations(results),
    }

    # Generate final recommendations
    summary["recommendations"] = generate_final_recommendations(summary)

    return summary


def identify_common_vulnerabilities(results: list) -> list[str]:
    """Identify patterns in vulnerabilities across scenarios"""
    vulnerabilities = []

    # Check for scenarios with high contamination
    high_contamination = [
        r for r in results if max(r["metrics"]["peer_table_contamination"]) > 0.5
    ]
    if high_contamination:
        vulnerabilities.append("High peer table contamination vulnerability")

    # Check for scenarios with low lookup success
    low_lookup = [r for r in results if min(r["metrics"]["lookup_success_rate"]) < 0.5]
    if low_lookup:
        vulnerabilities.append("DHT lookup disruption vulnerability")

    # Check for scenarios with poor connectivity
    poor_connectivity = [
        r for r in results if min(r["metrics"]["network_connectivity"]) < 0.5
    ]
    if poor_connectivity:
        vulnerabilities.append("Network connectivity fragmentation vulnerability")

    return vulnerabilities


def analyze_scale_impact(results: list) -> dict:
    """Analyze how network scale affects attack impact"""
    small_networks = [r for r in results if r["config"]["honest_nodes"] <= 10]
    medium_networks = [r for r in results if 10 < r["config"]["honest_nodes"] <= 50]
    large_networks = [r for r in results if r["config"]["honest_nodes"] > 50]

    def avg_resilience(networks):
        if not networks:
            return 0
        return sum(n["analysis"]["network_resilience_score"] for n in networks) / len(
            networks
        )

    return {
        "small_networks_avg_resilience": avg_resilience(small_networks),
        "medium_networks_avg_resilience": avg_resilience(medium_networks),
        "large_networks_avg_resilience": avg_resilience(large_networks),
        "scale_benefit": avg_resilience(large_networks)
        > avg_resilience(small_networks),
    }


def analyze_correlations(results: list) -> dict:
    """Analyze correlations between different metrics"""
    correlations = {}

    # Correlation between attack intensity and resilience
    intensities = [r["config"]["attack_intensity"] for r in results]
    resiliences = [r["analysis"]["network_resilience_score"] for r in results]

    # Simple correlation coefficient calculation
    intensity_resilience_corr = calculate_correlation(intensities, resiliences)
    correlations["intensity_vs_resilience"] = intensity_resilience_corr

    # Correlation between malicious ratio and impact
    malicious_ratios = [
        r["config"]["malicious_nodes"] / r["config"]["honest_nodes"] for r in results
    ]
    impacts = [100 - r["analysis"]["network_resilience_score"] for r in results]

    malicious_impact_corr = calculate_correlation(malicious_ratios, impacts)
    correlations["malicious_ratio_vs_impact"] = malicious_impact_corr

    return correlations


def calculate_correlation(x: list, y: list) -> float:
    """Calculate Pearson correlation coefficient"""
    if len(x) != len(y) or len(x) < 2:
        return 0.0

    n = len(x)
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_x2 = sum(xi**2 for xi in x)
    sum_y2 = sum(yi**2 for yi in y)

    numerator = n * sum_xy - sum_x * sum_y
    denominator = ((n * sum_x2 - sum_x**2) * (n * sum_y2 - sum_y**2)) ** 0.5

    return numerator / denominator if denominator != 0 else 0.0


@pytest.mark.trio
async def test_stress_test_multiple_runs():
    """Stress test running multiple attack scenarios repeatedly to ensure stability"""
    builder = AttackNetworkBuilder()
    total_runs = 5  # Run each scenario 5 times
    all_results = []

    for run_number in range(total_runs):
        logger.debug(f"Stress Test Run {run_number + 1}/{total_runs}")

        for config in ECLIPSE_ATTACK_CONFIGS[:3]:  # Test first 3 scenarios for speed
            honest_nodes = int(config["honest_nodes"])
            malicious_nodes = int(config["malicious_nodes"])
            attack_intensity = float(config["attack_intensity"])

            honest, malicious = await builder.create_eclipse_test_network(
                int(honest_nodes),
                int(malicious_nodes),
                float(attack_intensity),
            )

            scenario = EclipseScenario(honest, malicious)
            metrics = await scenario.execute()
            report = metrics.generate_attack_report()

            result = {
                "run_number": run_number + 1,
                "scenario_name": config["name"],
                "resilience_score": report["network_resilience_score"],
                "recovery_time": metrics.recovery_time,
                "affected_nodes": metrics.affected_nodes_percentage,
            }
            all_results.append(result)

            # Basic consistency check - resilience should be reasonable
            assert 0 <= float(result["resilience_score"]) <= 100
            assert float(result["recovery_time"]) > 0
            assert 0 <= float(result["affected_nodes"]) <= 100

    # Analyze consistency across runs
    scenario_groups = {}
    for result in all_results:
        key = result["scenario_name"]
        if key not in scenario_groups:
            scenario_groups[key] = []
        scenario_groups[key].append(result["resilience_score"])

    # Check that results are reasonably consistent (within 10% standard deviation)
    for scenario, scores in scenario_groups.items():
        if len(scores) > 1:
            mean_score = sum(scores) / len(scores)
            variance = sum((score - mean_score) ** 2 for score in scores) / len(scores)
            std_dev = variance**0.5
            consistency_ratio = std_dev / mean_score if mean_score > 0 else 0

            # Allow up to 15% variation for simulation consistency
            assert consistency_ratio < 0.15, (
                f"Scenario {scenario} shows inconsistency: {consistency_ratio:.3f}"
            )

    logger.debug(f"Stress test complete: {len(all_results)} scenarios run")
    logger.debug("All scenarios show consistent behavior across multiple runs")


def generate_final_recommendations(summary: dict) -> list[str]:
    """Generate final recommendations based on analysis"""
    recommendations = []

    # Based on resilience scores
    avg_resilience = summary["attack_effectiveness_analysis"][
        "average_resilience_score"
    ]
    if avg_resilience < 60:
        recommendations.append(
            "CRITICAL: Implement comprehensive peer validation and reputation systems"
        )
    elif avg_resilience < 80:
        recommendations.append(
            "HIGH: Strengthen DHT security and monitoring capabilities"
        )

    # Based on vulnerability patterns
    if summary["vulnerability_patterns"]["scale_impact"]["scale_benefit"]:
        recommendations.append(
            "Leverage network scale for improved resilience in large deployments"
        )

    # Based on correlations
    intensity_corr = summary["network_resilience_overview"]["correlation_analysis"][
        "intensity_vs_resilience"
    ]
    if abs(intensity_corr) > 0.7:
        recommendations.append(
            "Attack intensity is critical - prioritize intensity-based mitigations"
        )

    # Based on top recommendations
    top_recs = summary["mitigation_insights"]["top_recommendations"]
    for rec, count in top_recs[:3]:
        recommendations.append(f"Priority: {rec} (mentioned in {count} scenarios)")

    return recommendations
