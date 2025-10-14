"""
Attack Analysis Framework

This module provides a comprehensive framework for analyzing attack simulation results,
generating reports, and providing insights into network security and resilience.
"""

from typing import Any

from .attack_metrics import AttackMetrics


class AttackAnalysis:
    """Framework for analyzing attack simulation results"""

    def __init__(self):
        self.analysis_results = {}

    def generate_attack_report(self, metrics: AttackMetrics) -> dict[str, Any]:
        """Generate comprehensive attack analysis report"""
        return {
            "attack_effectiveness": self.calculate_effectiveness(metrics),
            "vulnerability_assessment": self.assess_vulnerabilities(metrics),
            "mitigation_recommendations": self.suggest_mitigations(metrics),
            "network_resilience_score": self.calculate_resilience(metrics),
            "security_insights": self.generate_security_insights(metrics),
            "risk_assessment": self.assess_overall_risk(metrics),
        }

    def calculate_effectiveness(self, metrics: AttackMetrics) -> dict[str, Any]:
        """Calculate attack effectiveness metrics"""
        effectiveness = {
            "time_to_partitioning": metrics.time_to_partitioning,
            "affected_nodes_percentage": metrics.affected_nodes_percentage,
            "attack_persistence": metrics.attack_persistence,
            "dht_poisoning_rate": metrics.dht_poisoning_rate,
            "routing_disruption_level": metrics.routing_disruption_level,
            "overall_effectiveness_score": self._calculate_effectiveness_score(metrics),
        }
        return effectiveness

    def assess_vulnerabilities(self, metrics: AttackMetrics) -> dict[str, Any]:
        """Assess network vulnerabilities based on metrics"""
        vulnerabilities = {
            "lookup_success_degradation": (
                metrics.lookup_success_rate[0] - metrics.lookup_success_rate[1]
                if len(metrics.lookup_success_rate) >= 2
                else 0
            ),
            "max_contamination": max(metrics.peer_table_contamination)
            if metrics.peer_table_contamination
            else 0,
            "connectivity_impact": (
                metrics.network_connectivity[0] - metrics.network_connectivity[1]
                if len(metrics.network_connectivity) >= 2
                else 0
            ),
            "resource_stress": (
                max(metrics.cpu_utilization) / metrics.cpu_utilization[0]
                if metrics.cpu_utilization
                else 1.0
            ),
            "vulnerability_severity": self._assess_vulnerability_severity(metrics),
        }
        return vulnerabilities

    def suggest_mitigations(self, metrics: AttackMetrics) -> list[str]:
        """Generate mitigation recommendations based on metrics"""
        recommendations = []

        if metrics.affected_nodes_percentage > 50:
            recommendations.append("Implement strict peer validation mechanisms")
        if metrics.routing_disruption_level > 0.5:
            recommendations.append("Add DHT entry verification and reputation systems")
        if max(metrics.peer_table_contamination) > 0.3:
            recommendations.append("Enable peer table monitoring and cleanup")
        if metrics.time_to_partitioning < 60:
            recommendations.append("Implement faster attack detection algorithms")
        if metrics.mitigation_effectiveness < 0.7:
            recommendations.append("Strengthen network segmentation and isolation")
        if metrics.attack_persistence > 0.8:
            recommendations.append(
                "Implement persistent attack monitoring and automated response"
            )
        if max(metrics.cpu_utilization) > 200:  # Assuming baseline is 100%
            recommendations.append("Add rate limiting and resource monitoring")

        return recommendations

    def calculate_resilience(self, metrics: AttackMetrics) -> float:
        """Calculate overall network resilience score (0-100)"""
        base_score = 100.0

        # Penalize for various attack impacts
        lookup_penalty = (
            (metrics.lookup_success_rate[0] - metrics.lookup_success_rate[1]) * 50
            if len(metrics.lookup_success_rate) >= 2
            else 0
        )
        contamination_penalty = (
            max(metrics.peer_table_contamination) * 30
            if metrics.peer_table_contamination
            else 0
        )
        connectivity_penalty = (
            (metrics.network_connectivity[0] - metrics.network_connectivity[1]) * 20
            if len(metrics.network_connectivity) >= 2
            else 0
        )
        resource_penalty = (
            (max(metrics.cpu_utilization) / metrics.cpu_utilization[0] - 1) * 10
            if metrics.cpu_utilization
            else 0
        )

        resilience_score = (
            base_score
            - lookup_penalty
            - contamination_penalty
            - connectivity_penalty
            - resource_penalty
        )
        return max(0.0, min(100.0, resilience_score))

    def generate_security_insights(self, metrics: AttackMetrics) -> dict[str, Any]:
        """Generate security insights and analysis"""
        insights = {
            "attack_patterns": self._identify_attack_patterns(metrics),
            "weak_points": self._identify_weak_points(metrics),
            "defense_effectiveness": self._evaluate_defense_effectiveness(metrics),
            "improvement_priorities": self._prioritize_improvements(metrics),
        }
        return insights

    def assess_overall_risk(self, metrics: AttackMetrics) -> dict[str, Any]:
        """Assess overall security risk"""
        resilience_score = self.calculate_resilience(metrics)

        if resilience_score >= 80:
            risk_level = "Low"
            risk_description = "Network shows strong resilience to attacks"
        elif resilience_score >= 60:
            risk_level = "Medium"
            risk_description = (
                "Network has moderate vulnerabilities that should be addressed"
            )
        elif resilience_score >= 40:
            risk_level = "High"
            risk_description = "Network is significantly vulnerable to attacks"
        else:
            risk_level = "Critical"
            risk_description = "Network requires immediate security improvements"

        return {
            "risk_level": risk_level,
            "risk_description": risk_description,
            "resilience_score": resilience_score,
            "critical_findings": self._identify_critical_findings(metrics),
        }

    def _calculate_effectiveness_score(self, metrics: AttackMetrics) -> float:
        """Calculate overall attack effectiveness score (0-100)"""
        score = 0

        # Time to partitioning (faster = more effective)
        if metrics.time_to_partitioning < 30:
            score += 30
        elif metrics.time_to_partitioning < 60:
            score += 20
        elif metrics.time_to_partitioning < 120:
            score += 10

        # Affected nodes percentage
        score += metrics.affected_nodes_percentage * 0.3

        # Attack persistence
        score += metrics.attack_persistence * 20

        # Routing disruption
        score += metrics.routing_disruption_level * 20

        return min(100.0, score)

    def _assess_vulnerability_severity(self, metrics: AttackMetrics) -> str:
        """Assess vulnerability severity level"""
        severity_score = 0

        if len(metrics.lookup_success_rate) >= 2:
            degradation = (
                metrics.lookup_success_rate[0] - metrics.lookup_success_rate[1]
            )
            severity_score += degradation * 25

        if metrics.peer_table_contamination:
            severity_score += max(metrics.peer_table_contamination) * 25

        if len(metrics.network_connectivity) >= 2:
            impact = metrics.network_connectivity[0] - metrics.network_connectivity[1]
            severity_score += impact * 25

        if metrics.cpu_utilization:
            stress = max(metrics.cpu_utilization) / metrics.cpu_utilization[0]
            severity_score += (stress - 1) * 25

        if severity_score < 25:
            return "Low"
        elif severity_score < 50:
            return "Medium"
        elif severity_score < 75:
            return "High"
        else:
            return "Critical"

    def _identify_attack_patterns(self, metrics: AttackMetrics) -> list[str]:
        """Identify patterns in attack behavior"""
        patterns = []

        if metrics.dht_poisoning_rate > 0.5:
            patterns.append("High DHT poisoning activity detected")
        if metrics.peer_table_flooding_rate > 10:
            patterns.append("Peer table flooding attack pattern")
        if metrics.routing_disruption_level > 0.7:
            patterns.append("Severe routing disruption pattern")
        if metrics.attack_persistence > 0.8:
            patterns.append("Persistent attack pattern requiring long-term monitoring")

        return patterns

    def _identify_weak_points(self, metrics: AttackMetrics) -> list[str]:
        """Identify network weak points"""
        weak_points = []

        if (
            len(metrics.lookup_success_rate) >= 2
            and metrics.lookup_success_rate[1] < 0.5
        ):
            weak_points.append("DHT lookup reliability under attack")
        if max(metrics.peer_table_contamination) > 0.5:
            weak_points.append("Peer table integrity compromised")
        if (
            len(metrics.network_connectivity) >= 2
            and metrics.network_connectivity[1] < 0.5
        ):
            weak_points.append("Network connectivity fragmentation")
        if metrics.recovery_time > 300:  # 5 minutes
            weak_points.append("Slow recovery mechanisms")

        return weak_points

    def _evaluate_defense_effectiveness(self, metrics: AttackMetrics) -> dict[str, Any]:
        """Evaluate effectiveness of defense mechanisms"""
        effectiveness = {
            "detection_speed": "Fast" if metrics.detection_time < 30 else "Slow",
            "recovery_speed": "Fast" if metrics.recovery_time < 120 else "Slow",
            "mitigation_strength": "Strong"
            if metrics.mitigation_effectiveness > 0.8
            else "Weak",
            "overall_defense_rating": self._calculate_defense_rating(metrics),
        }
        return effectiveness

    def _prioritize_improvements(self, metrics: AttackMetrics) -> list[str]:
        """Prioritize security improvements"""
        priorities = []

        if metrics.detection_time > 60:
            priorities.append("High: Improve attack detection speed")
        if metrics.mitigation_effectiveness < 0.7:
            priorities.append("High: Strengthen mitigation strategies")
        if max(metrics.peer_table_contamination) > 0.3:
            priorities.append("Medium: Enhance peer validation")
        if metrics.recovery_time > 180:
            priorities.append("Medium: Optimize recovery procedures")

        return priorities

    def _calculate_defense_rating(self, metrics: AttackMetrics) -> str:
        """Calculate overall defense rating"""
        rating_score = 0

        if metrics.detection_time < 30:
            rating_score += 25
        elif metrics.detection_time < 60:
            rating_score += 15

        if metrics.mitigation_effectiveness > 0.8:
            rating_score += 25
        elif metrics.mitigation_effectiveness > 0.6:
            rating_score += 15

        if metrics.recovery_time < 120:
            rating_score += 25
        elif metrics.recovery_time < 300:
            rating_score += 15

        if rating_score >= 50:
            return "Excellent"
        elif rating_score >= 35:
            return "Good"
        elif rating_score >= 20:
            return "Fair"
        else:
            return "Poor"

    def _identify_critical_findings(self, metrics: AttackMetrics) -> list[str]:
        """Identify critical security findings"""
        findings = []

        if (
            len(metrics.lookup_success_rate) >= 2
            and metrics.lookup_success_rate[1] < 0.3
        ):
            findings.append("Critical: DHT lookups fail catastrophically under attack")
        if metrics.affected_nodes_percentage > 80:
            findings.append("Critical: Majority of network nodes compromised")
        if metrics.time_to_partitioning < 30:
            findings.append("Critical: Network partitions extremely quickly")
        if metrics.mitigation_effectiveness < 0.5:
            findings.append("Critical: Defense mechanisms largely ineffective")

        return findings
