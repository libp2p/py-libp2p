"""Terminal UI for live connection health monitoring."""

from __future__ import annotations

import sys

import trio

from libp2p.abc import IHost

from .health_view import build_peer_table, get_network_summary_dict


def _format_table(rows: list[dict[str, object]], summary: dict[str, object]) -> str:
    headers = (
        "peer_id",
        "conns",
        "score",
        "latency_ms",
        "success",
        "prot",
        "unhl",
    )
    lines = [
        "Connection health (Ctrl+C to quit)",
        f"Peers: {summary.get('total_peers', 0)}  "
        f"Connections: {summary.get('total_connections', 0)}  "
        f"Avg health: {summary.get('average_peer_health', 0.0):.3f}",
        "",
        "  ".join(f"{h:>12}" for h in headers),
        "-" * 90,
    ]
    for row in rows:
        lines.append(
            "  ".join(
                [
                    f"{str(row.get('peer_id', '')):>12}"[:12],
                    f"{row.get('connections', 0)!s:>12}",
                    f"{row.get('score', 0)!s:>12}",
                    f"{row.get('latency_ms', 0)!s:>12}",
                    f"{row.get('success_rate', 0)!s:>12}",
                    f"{'Y' if row.get('protected') else 'N':>12}",
                    f"{row.get('unhealthy', 0)!s:>12}",
                ]
            )
        )
    return "\n".join(lines)


async def run_health_tui(host: IHost, refresh_interval: float = 1.0) -> None:
    """Refresh a terminal table until cancelled."""
    try:
        from rich.console import Console
        from rich.live import Live
        from rich.table import Table
    except ImportError:
        try:
            while True:
                summary = get_network_summary_dict(host)
                rows = build_peer_table(host)
                sys.stdout.write("\033[2J\033[H")
                sys.stdout.write(_format_table(rows, summary) + "\n")
                sys.stdout.flush()
                await trio.sleep(refresh_interval)
        except trio.Cancelled:
            return
        return

    console = Console()

    def render_rich() -> Table:
        table = Table(title="py-libp2p connection health")
        for col in (
            "peer_id",
            "conns",
            "score",
            "latency_ms",
            "success",
            "protected",
            "unhealthy",
        ):
            table.add_column(col)
        summary = get_network_summary_dict(host)
        for row in build_peer_table(host):
            table.add_row(
                str(row["peer_id"]),
                str(row["connections"]),
                str(row["score"]),
                str(row["latency_ms"]),
                str(row["success_rate"]),
                "Y" if row["protected"] else "N",
                str(row["unhealthy"]),
            )
        table.caption = (
            f"Peers={summary.get('total_peers', 0)} "
            f"Conns={summary.get('total_connections', 0)} "
            f"Avg={summary.get('average_peer_health', 0.0):.3f}"
        )
        return table

    with Live(render_rich(), console=console, refresh_per_second=1) as live:
        try:
            while True:
                await trio.sleep(refresh_interval)
                live.update(render_rich())
        except trio.Cancelled:
            return
