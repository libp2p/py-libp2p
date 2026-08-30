#!/usr/bin/env python3
"""
Profile pubsub tests that dominate Windows CI runtime.

Usage (from repo root, with dev deps installed):

    python scripts/ci/profile_pubsub_tests.py
    python scripts/ci/profile_pubsub_tests.py --cprofile test_gossip_heartbeat[4]
    python scripts/ci/profile_pubsub_tests.py --benchmark-ids

See docs/ci/windows-test-performance.md for analysis and recommendations.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_TESTS = [
    "tests/core/pubsub/test_gossipsub.py::test_gossip_heartbeat[4]",
    "tests/core/pubsub/test_gossipsub.py::test_mesh_heartbeat[10]",
    "tests/core/pubsub/test_gossipsub.py::test_fanout",
    "tests/core/pubsub/test_gossipsub.py::test_fanout_maintenance",
]


def benchmark_identity_generation() -> None:
    from libp2p import generate_new_ed25519_identity, generate_new_rsa_identity
    from tests.utils.factories import IDFactory

    print("Identity generation benchmark (28 IDs, typical gossip_heartbeat test):")
    for label, fn in [
        ("IDFactory (RSA via factory)", lambda: [IDFactory() for _ in range(28)]),
        (
            "generate_new_rsa_identity",
            lambda: [generate_new_rsa_identity() for _ in range(28)],
        ),
        (
            "generate_new_ed25519_identity",
            lambda: [generate_new_ed25519_identity() for _ in range(28)],
        ),
    ]:
        start = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - start
        print(f"  {label:32s} {elapsed:7.3f}s")


def run_pytest_durations(tests: list[str]) -> int:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *tests,
        "-v",
        "--durations=15",
        "--timeout=1200",
    ]
    print("Running:", " ".join(cmd))
    return subprocess.call(cmd, cwd=REPO_ROOT)


def run_cprofile(nodeid: str) -> int:
    cmd = [
        sys.executable,
        "-m",
        "cProfile",
        "-s",
        "cumtime",
        "-m",
        "pytest",
        nodeid,
        "-q",
        "--timeout=1200",
    ]
    print("Running:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    print("\n--- RSA / factory hotspots ---")
    for line in proc.stdout.splitlines():
        lower = line.lower()
        if any(k in lower for k in ("rsa", "factory", "listen", "sleep", "gossip")):
            print(line)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark-ids",
        action="store_true",
        help="Benchmark RSA vs Ed25519 peer ID generation only",
    )
    parser.add_argument(
        "--cprofile",
        metavar="NODEID",
        help="Run cProfile on a single pytest node id",
    )
    parser.add_argument(
        "tests",
        nargs="*",
        help="Pytest node ids (default: slow gossipsub subset)",
    )
    args = parser.parse_args()

    if args.benchmark_ids:
        benchmark_identity_generation()
        return 0

    if args.cprofile:
        return run_cprofile(args.cprofile)

    tests = args.tests or DEFAULT_TESTS
    benchmark_identity_generation()
    print()
    return run_pytest_durations(tests)


if __name__ == "__main__":
    raise SystemExit(main())
