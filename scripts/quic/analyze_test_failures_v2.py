#!/usr/bin/env python3
"""Analyze test_yamux_stress_ping failures to identify patterns."""

from collections import Counter, defaultdict
import re
import subprocess
import sys
from typing import Any


def run_test(run_num: int) -> tuple[bool, str]:
    """Run the test once and return (success, output)."""
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".txt") as f:
        output_file = f.name

    try:
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
            env={**os.environ, "LIBP2P_DEBUG": "libp2p.host:ERROR"},
            stdout=open(output_file, "w"),
            stderr=subprocess.STDOUT,
            text=True,
            timeout=240,
        )

        with open(output_file) as f:
            output = f.read()

        return result.returncode == 0, output
    finally:
        if os.path.exists(output_file):
            os.unlink(output_file)


def extract_failure_info(output: str) -> dict[str, Any]:
    """Extract failure information from test output."""
    info = {
        "failed_streams": [],
        "successful_pings": 0,
        "total_streams": 0,
        "error_messages": [],
        "registry_stats": {},
        "lock_stats": {},
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

    # Extract MultiselectClientError details
    multiselect_errors = re.findall(
        r"MultiselectClientError: (.*?)(?:\n|$)", output, re.MULTILINE
    )
    info["multiselect_errors"] = multiselect_errors

    # Extract registry lock stats
    max_wait_match = re.search(r"Max Wait Time: ([\d.]+)ms", output)
    if max_wait_match:
        info["lock_stats"]["max_wait_time_ms"] = float(max_wait_match.group(1))

    max_hold_match = re.search(r"Max Hold Time: ([\d.]+)ms", output)
    if max_hold_match:
        info["lock_stats"]["max_hold_time_ms"] = float(max_hold_match.group(1))

    max_concurrent_match = re.search(r"Max Concurrent Holds: (\d+)", output)
    if max_concurrent_match:
        info["lock_stats"]["max_concurrent_holds"] = int(max_concurrent_match.group(1))

    fallback_match = re.search(r"Fallback Routing Count: (\d+)", output)
    if fallback_match:
        info["registry_stats"]["fallback_routing_count"] = int(fallback_match.group(1))

    return info


def analyze_patterns(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze patterns across multiple test runs."""
    analysis = {
        "total_runs": len(results),
        "pass_count": sum(1 for r in results if r.get("success", False)),
        "fail_count": sum(1 for r in results if not r.get("success", False)),
        "common_failed_indices": Counter(),
        "error_types": Counter(),
        "lock_performance": defaultdict(list),
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

            # Collect multiselect errors
            for error in failure_info.get("multiselect_errors", []):
                analysis["error_types"]["multiselect_detailed"] += 1

            # Collect lock stats
            lock_stats = failure_info.get("lock_stats", {})
            for key, value in lock_stats.items():
                if isinstance(value, (int, float)):
                    analysis["lock_performance"][key].append(value)

            # Collect registry stats
            registry_stats = failure_info.get("registry_stats", {})
            for key, value in registry_stats.items():
                if isinstance(value, (int, float)):
                    analysis["registry_performance"][key].append(value)

    return analysis


def main():
    num_runs = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    print("=" * 80)
    print(f"Running {num_runs} test iterations for pattern analysis...")
    print("=" * 80)

    results = []
    for i in range(1, num_runs + 1):
        print(f"Run {i}/{num_runs}...", end=" ", flush=True)
        try:
            success, output = run_test(i)
            result = {"success": success, "run": i}

            if not success:
                result["failure_info"] = extract_failure_info(output)
                failed_count = len(result["failure_info"].get("failed_streams", []))
                successful = result["failure_info"].get("successful_pings", 0)
                total = result["failure_info"].get("total_streams", 0)
                print(
                    f"FAILED ({successful}/{total} successful, "
                    f"{failed_count} failed streams)"
                )
            else:
                print("PASSED")

            results.append(result)
        except subprocess.TimeoutExpired:
            print("TIMEOUT")
            results.append({"success": False, "run": i, "timeout": True})
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({"success": False, "run": i, "error": str(e)})

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

        if analysis["common_failed_indices"]:
            print("\nMost Frequently Failed Stream Indices (top 15):")
            for idx, count in analysis["common_failed_indices"].most_common(15):
                print(f"  Stream #{idx}: failed {count} times")

        if analysis["lock_performance"]:
            print("\nLock Performance (from failures):")
            for key, values in analysis["lock_performance"].items():
                if values:
                    avg = sum(values) / len(values)
                    min_val = min(values)
                    max_val = max(values)
                    print(
                        f"  {key}: avg={avg:.2f}, min={min_val:.2f}, max={max_val:.2f}"
                    )

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
                print(f"  Failed indices: {info['failed_streams'][:15]}...")
            if info.get("multiselect_errors"):
                print(f"  Multiselect errors: {info['multiselect_errors'][:2]}")
            if info.get("lock_stats"):
                print(f"  Lock stats: {info['lock_stats']}")


if __name__ == "__main__":
    main()
