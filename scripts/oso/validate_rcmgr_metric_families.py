#!/usr/bin/env python3
"""Ad-hoc smoke test for rcmgr metric families used in OSO reports."""

from __future__ import annotations

from argparse import ArgumentParser

from libp2p.observability.oso.metrics import collect_rcmgr_baseline
from libp2p.rcmgr.metrics import Metrics
from libp2p.rcmgr.prometheus_exporter import PROMETHEUS_AVAILABLE, PrometheusExporter

EXPECTED_METRIC_FAMILIES = [
    "libp2p_rcmgr_connections",
    "libp2p_rcmgr_streams",
    "libp2p_rcmgr_memory",
    "libp2p_rcmgr_fds",
    "libp2p_rcmgr_blocked_resources",
]


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        description="Validate rcmgr metric families before OSO report delivery",
    )
    parser.add_argument(
        "--require-prometheus",
        action="store_true",
        help="Fail if Prometheus exporter support is not available",
    )
    parser.add_argument(
        "--verify-exporter-text",
        action="store_true",
        help=(
            "If Prometheus is available, instantiate exporter and verify metric "
            "family names appear in rendered Prometheus text output"
        ),
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    errors: list[str] = []

    baseline = collect_rcmgr_baseline()
    print(f"[INFO] metrics_available={baseline.metrics_available}")
    print(f"[INFO] prometheus_available={baseline.prometheus_available}")
    print(f"[INFO] prometheus_runtime_available={PROMETHEUS_AVAILABLE}")
    print(f"[INFO] monitoring_available={baseline.monitoring_available}")
    print(
        "[INFO] exported_metric_names="
        + (", ".join(baseline.exported_metric_names) or "none")
    )

    if not baseline.metrics_available:
        errors.append("rcmgr Metrics capability is unavailable")

    if args.require_prometheus and not PROMETHEUS_AVAILABLE:
        errors.append(
            "Prometheus runtime support is required but unavailable "
            "(install prometheus_client)"
        )

    missing_declared = [
        name
        for name in EXPECTED_METRIC_FAMILIES
        if name not in baseline.exported_metric_names
    ]
    if baseline.prometheus_available and missing_declared:
        errors.append(
            "Missing expected metric families in exported_metric_names: "
            + ", ".join(missing_declared)
        )

    if args.verify_exporter_text and PROMETHEUS_AVAILABLE:
        try:
            exporter = PrometheusExporter(enable_server=False)
            exporter.update_from_metrics(Metrics())
            payload = exporter.get_metrics_text()
            missing_in_payload = [
                name for name in EXPECTED_METRIC_FAMILIES if name not in payload
            ]
            if missing_in_payload:
                errors.append(
                    "Missing expected metric families in exporter output: "
                    + ", ".join(missing_in_payload)
                )
            else:
                print("[INFO] exporter text contains all expected metric families")
        except Exception as error:  # pragma: no cover - defensive smoke-check handling
            errors.append(f"Failed exporter text validation: {error}")
    elif args.verify_exporter_text:
        errors.append(
            "Cannot verify exporter text without prometheus_client runtime support"
        )

    if errors:
        for entry in errors:
            print(f"[ERROR] {entry}")
        print(f"[RESULT] FAILED ({len(errors)} issue(s))")
        return 1

    print("[RESULT] PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
