import math

import pytest

from .partition_attack import NetworkPartitioner, TopologyPartitionScenario


@pytest.mark.trio
async def test_network_partitioner_basic_partition():
    nodes = [f"p{i}" for i in range(6)]
    partitions = [["p0", "p1", "p2"], ["p3", "p4", "p5"]]

    attacker = NetworkPartitioner(nodes, partitions, intensity=1.0)
    cut_edges, remaining_edges = await attacker.apply_partition()

    assert len(cut_edges) > 0
    assert len(remaining_edges) > 0

    total_edges = len(cut_edges) + len(remaining_edges)
    expected_edges = math.comb(len(nodes), 2)
    assert total_edges == expected_edges


@pytest.mark.trio
async def test_partition_scenario_execution():
    nodes = [f"p{i}" for i in range(6)]
    partitions = [["p0", "p1", "p2"], ["p3", "p4", "p5"]]

    attacker = NetworkPartitioner(nodes, partitions, intensity=1.0)
    scenario = TopologyPartitionScenario(nodes, attacker)

    result = await scenario.run()
    assert "cut_edges" in result
    assert "remaining_edges" in result
    assert "cut_ratio" in result
    assert "attack_metrics" in result
    assert 0.0 <= result["cut_ratio"] <= 1.0


@pytest.mark.trio
async def test_partition_resilience_decreases_with_cut_ratio():
    nodes = [f"p{i}" for i in range(8)]
    # two strongly separated groups
    partitions = [["p0", "p1", "p2", "p3"], ["p4", "p5", "p6", "p7"]]

    attacker = NetworkPartitioner(nodes, partitions, intensity=1.0)
    scenario = TopologyPartitionScenario(nodes, attacker)

    result = await scenario.run()
    report = result["attack_metrics"]
    resilience = report["resilience_score"]

    assert resilience <= 1.0
    assert resilience < 0.8  # strong partitioning should reduce resilience


@pytest.mark.trio
async def test_partition_metrics_fields_present():
    nodes = [f"p{i}" for i in range(5)]
    partitions = [["p0", "p1"], ["p2", "p3", "p4"]]

    attacker = NetworkPartitioner(nodes, partitions, intensity=1.0)
    scenario = TopologyPartitionScenario(nodes, attacker)

    result = await scenario.run()
    report = result["attack_metrics"]

    required_fields = [
        "partition_cut_ratio",
        "lookup_success_degradation",
        "routing_incorrect_rate",
        "lookup_failure_rate",
        "avg_lookup_latency",
        "resilience_score",
        "network_connectivity",
        "peer_table_contamination",
        "affected_nodes_percentage",
    ]

    for field in required_fields:
        assert field in report, f"Missing metric field: {field}"


@pytest.mark.trio
async def test_partition_full_mesh_edge_count_consistency():
    nodes = [f"p{i}" for i in range(7)]
    partitions = [["p0", "p1", "p2"], ["p3", "p4", "p5", "p6"]]

    attacker = NetworkPartitioner(nodes, partitions, intensity=1.0)
    cut_edges, remaining_edges = await attacker.apply_partition()

    total_edges = len(cut_edges) + len(remaining_edges)
    expected_edges = math.comb(len(nodes), 2)
    assert total_edges == expected_edges


@pytest.mark.trio
async def test_partition_no_cut_when_single_partition():
    nodes = [f"p{i}" for i in range(5)]
    partitions = [nodes[:]]  # all in one group

    attacker = NetworkPartitioner(nodes, partitions, intensity=1.0)
    cut_edges, remaining_edges = await attacker.apply_partition()

    assert len(cut_edges) == 0
    assert len(remaining_edges) == math.comb(len(nodes), 2)


@pytest.mark.trio
async def test_partition_affected_nodes_percentage_reasonable():
    nodes = [f"p{i}" for i in range(6)]
    partitions = [["p0", "p1", "p2"], ["p3", "p4", "p5"]]

    attacker = NetworkPartitioner(nodes, partitions, intensity=1.0)
    scenario = TopologyPartitionScenario(nodes, attacker)

    result = await scenario.run()
    report = result["attack_metrics"]

    assert 0.0 <= report["affected_nodes_percentage"] <= 100.0
