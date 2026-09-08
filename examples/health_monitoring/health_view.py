"""Shared helpers for health monitoring demo views."""

from __future__ import annotations

from typing import Any

from libp2p.abc import IHost


def build_peer_table(host: IHost) -> list[dict[str, Any]]:
    """Build per-peer rows for TUI / web tables."""
    summary = host.get_network_health_summary()
    rows: list[dict[str, Any]] = []
    swarm = host.get_network()
    tag_store = getattr(swarm, "tag_store", None)

    for detail in summary.get("peer_details", []):
        peer_id_str = str(detail.get("peer_id", ""))
        protected = False
        if tag_store is not None:
            try:
                from libp2p.peer.id import ID

                protected = tag_store.is_protected(ID.from_string(peer_id_str))
            except Exception:
                protected = False

        unhealthy = int(detail.get("unhealthy_connections", 0))
        rows.append(
            {
                "peer_id": peer_id_str[:20],
                "connections": detail.get("connection_count", 0),
                "score": round(float(detail.get("average_health_score", 0.0)), 3),
                "latency_ms": round(float(detail.get("average_latency_ms", 0.0)), 1),
                "success_rate": round(
                    float(detail.get("average_success_rate", 0.0)), 3
                ),
                "protected": protected,
                "unhealthy": unhealthy,
            }
        )

    return rows


def get_metrics_snapshot(host: IHost, format: str = "json") -> str:
    """Return exported metrics from the host."""
    return host.export_health_metrics(format)


def get_network_summary_dict(host: IHost) -> dict[str, Any]:
    """Return the network health summary as a dict."""
    return host.get_network_health_summary()
