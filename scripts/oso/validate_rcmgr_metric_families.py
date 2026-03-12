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


def _parse_prometheus_sample(line: str) -> tuple[str, float] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    parts = line.split()
    if len(parts) < 2:
        return None

    metric_with_labels, value_text = parts[0], parts[1]
    metric_name = metric_with_labels.split("{", 1)[0]
    try:
        value = float(value_text)
    except ValueError:
        return None
    return metric_name, value


def _collect_family_samples(payload: str) -> dict[str, list[tuple[str, float]]]:
    samples_by_family = {family: [] for family in EXPECTED_METRIC_FAMILIES}
    for line in payload.splitlines():
        parsed = _parse_prometheus_sample(line)
        if parsed is None:
            continue

        metric_name, value = parsed
        for family in EXPECTED_METRIC_FAMILIES:
            if metric_name == family or metric_name.startswith(f"{family}_"):
                samples_by_family[family].append((metric_name, value))
                break
    return samples_by_family


def _print_family_samples(
    samples_by_family: dict[str, list[tuple[str, float]]],
) -> None:
    print("[INFO] metric family samples from exporter text:")
    for family in EXPECTED_METRIC_FAMILIES:
        samples = samples_by_family.get(family, [])
        if not samples:
            print(f"[INFO]   {family}: no numeric samples found")
            continue

        preview = ", ".join(
            f"{metric_name}={value:g}" for metric_name, value in samples[:3]
        )
        if len(samples) > 3:
            preview += ", ..."
        print(f"[INFO]   {family}: {preview}")


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
                _print_family_samples(_collect_family_samples(payload))
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
