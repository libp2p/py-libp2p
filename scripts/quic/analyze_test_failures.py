#!/usr/bin/env python3
"""Analyze test_yamux_stress_ping failures to identify patterns."""

from collections import Counter, defaultdict
import json
import re
import subprocess
from typing import Any


def run_test() -> tuple[bool, str]:
    """Run the test once and return (success, output)."""
    result = subprocess.run(
        [
            "python",
            "-m",
            "pytest",
            "tests/core/transport/quic/test_integration.py::test_yamux_stress_ping",
            "-v",
            "--tb=line",
            "-p",
            "no:rerunfailures",
        ],
        env={"LIBP2P_DEBUG": "libp2p.host:ERROR"},
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stdout + result.stderr


def extract_failure_info(output: str) -> dict[str, Any]:
    """Extract failure information from test output."""
    info = {
        "failed_streams": [],
        "successful_pings": 0,
        "total_streams": 0,
        "error_messages": [],
        "registry_stats": {},
    }

    # Extract failed stream indices
    failed_match = re.search(r"Failed stream indices: \[(.*?)\]", output)
    if failed_match:
        indices_str = failed_match.group(1)
        info["failed_streams"] = [
            int(x.strip()) for x in indices_str.split(",") if x.strip()
        ]

    # Extract ping counts
    success_match = re.search(r"Successful Pings: (\d+)", output)
    if success_match:
        info["successful_pings"] = int(success_match.group(1))

    total_match = re.search(r"Total Streams Launched: (\d+)", output)
    if total_match:
        info["total_streams"] = int(total_match.group(1))

    # Extract error messages
    error_pattern = r"Failed to open stream.*?Error: (.*?)(?:\n|$)"
    errors = re.findall(error_pattern, output, re.MULTILINE | re.DOTALL)
    info["error_messages"] = errors

    # Extract registry stats if available
    stats_match = re.search(
        r"Registry Performance Stats.*?(\{.*?\})", output, re.DOTALL
    )
    if stats_match:
        try:
            info["registry_stats"] = json.loads(stats_match.group(1))
        except Exception:
            pass

    return info


def analyze_patterns(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze patterns across multiple test runs."""
    analysis = {
        "total_runs": len(results),
        "pass_count": sum(1 for r in results if r.get("success", False)),
        "fail_count": sum(1 for r in results if not r.get("success", False)),
        "common_failed_indices": Counter(),
        "error_types": Counter(),
        "registry_performance": defaultdict(list),
    }

    for result in results:
        if not result.get("success", False):
            failure_info = result.get("failure_info", {})

            # Track which stream indices fail most often
            for idx in failure_info.get("failed_streams", []):
                analysis["common_failed_indices"][idx] += 1

            # Categorize errors
            for error in failure_info.get("error_messages", []):
                error_lower = error.lower()
                if "timeout" in error_lower or "timed out" in error_lower:
                    analysis["error_types"]["timeout"] += 1
                elif "protocol" in error_lower or "not supported" in error_lower:
                    analysis["error_types"]["protocol_error"] += 1
                elif "multiselect" in error_lower:
                    analysis["error_types"]["multiselect_error"] += 1
                else:
                    analysis["error_types"]["other"] += 1

            # Collect registry stats
            stats = failure_info.get("registry_stats", {})
            if stats:
                for key, value in stats.items():
                    if isinstance(value, (int, float)):
                        analysis["registry_performance"][key].append(value)

    return analysis


def main():
    print("=" * 80)
    print("Running 30 test iterations for pattern analysis...")
    print("=" * 80)

    results = []
    for i in range(1, 31):
        print(f"Run {i}/30...", end=" ", flush=True)
        success, output = run_test()
        result = {"success": success, "run": i}

        if not success:
            result["failure_info"] = extract_failure_info(output)
            failed_count = len(result["failure_info"].get("failed_streams", []))
            print(f"FAILED ({failed_count} streams failed)")
        else:
            print("PASSED")

        results.append(result)

    print("\n" + "=" * 80)
    print("ANALYSIS RESULTS")
    print("=" * 80)

    analysis = analyze_patterns(results)

    print("\nOverall Statistics:")
    print(f"  Total runs: {analysis['total_runs']}")
    pass_pct = analysis["pass_count"] * 100 // analysis["total_runs"]
    print(f"  Passed: {analysis['pass_count']} ({pass_pct}%)")
    fail_pct = analysis["fail_count"] * 100 // analysis["total_runs"]
    print(f"  Failed: {analysis['fail_count']} ({fail_pct}%)")

    if analysis["fail_count"] > 0:
        print("\nError Type Distribution:")
        for error_type, count in analysis["error_types"].most_common():
            print(f"  {error_type}: {count}")

        print("\nMost Frequently Failed Stream Indices (top 10):")
        for idx, count in analysis["common_failed_indices"].most_common(10):
            print(f"  Stream #{idx}: failed {count} times")

        if analysis["registry_performance"]:
            print("\nRegistry Performance (from failures):")
            for key, values in analysis["registry_performance"].items():
                if values:
                    avg = sum(values) / len(values)
                    print(
                        f"  {key}: avg={avg:.2f}, min={min(values)}, max={max(values)}"
                    )

    print("\n" + "=" * 80)
    print("Detailed failure information from last 5 failures:")
    print("=" * 80)

    failure_count = 0
    for result in reversed(results):
        if not result.get("success", False) and failure_count < 5:
            failure_count += 1
            info = result.get("failure_info", {})
            print(f"\nFailure #{failure_count} (Run {result['run']}):")
            print(f"  Failed streams: {len(info.get('failed_streams', []))}")
            successful = info.get("successful_pings", 0)
            total = info.get("total_streams", 0)
            print(f"  Successful: {successful}/{total}")
            if info.get("failed_streams"):
                print(f"  Failed indices: {info['failed_streams'][:10]}...")
            if info.get("error_messages"):
                print(f"  Sample error: {info['error_messages'][0][:100]}...")


if __name__ == "__main__":
    main()
