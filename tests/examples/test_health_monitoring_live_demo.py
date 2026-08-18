"""Smoke tests for the live health-monitoring demo."""

from __future__ import annotations

import pytest

from examples.health_monitoring.live_demo import (
    ALL_SCENARIOS,
    build_parser,
    parse_scenarios,
    run_live_demo,
)


def test_parse_scenarios_all() -> None:
    assert parse_scenarios("all") == ALL_SCENARIOS
    assert parse_scenarios("") == ALL_SCENARIOS
    assert parse_scenarios(["all"]) == ALL_SCENARIOS


def test_parse_scenarios_subset_and_unknown() -> None:
    assert parse_scenarios("healthy,protect") == ("healthy", "protect")
    assert parse_scenarios("churn healthy") == ("churn", "healthy")
    with pytest.raises(ValueError, match="Unknown scenario"):
        parse_scenarios("healthy,nope")


def test_parser_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.peers == 25
    assert args.scenario == "all"


@pytest.mark.trio
async def test_live_health_demo_connects_and_reports() -> None:
    result = await run_live_demo(
        peers=4,
        scenarios="all",
        wait_for_monitor=1.2,
        protect_count=1,
        churn_count=1,
        streams_per_peer=2,
    )

    assert result["peers"] == 4
    assert result["scenarios"] == list(ALL_SCENARIOS)
    assert result["echoed"] == b"health-demo"
    assert result["protected"] is True

    healthy = result["healthy"]
    assert healthy["echo_ok"] == 3
    assert healthy["total_connections"] >= 3
    assert healthy["monitor_status"].get("enabled") is True
    assert healthy["network_health"].get("total_connections", 0) >= 3
    assert "average_peer_health" in healthy["network_health"]
    assert "average_health_score" in healthy["peer_health"]

    assert result["protect"]["protected_count"] == 1
    assert result["traffic"]["echo_ok"] == 6
    assert result["churn"]["churned"] == 1
    assert result["churn"]["connections_after"] < result["churn"]["connections_before"]
    assert result["disabled"]["observer_health"] == {}
    assert result["disabled"]["observer_connections"] >= 1


@pytest.mark.trio
async def test_live_health_demo_healthy_only() -> None:
    result = await run_live_demo(
        peers=3,
        scenarios="healthy",
        wait_for_monitor=1.0,
    )

    assert result["scenarios"] == ["healthy"]
    assert result["total_connections"] >= 2
    assert result["monitor_status"].get("enabled") is True
    assert "protect" not in result
    assert "churn" not in result
