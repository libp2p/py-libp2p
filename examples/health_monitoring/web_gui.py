"""Local web UI for live connection health monitoring."""

from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import trio

from libp2p.abc import IHost

from .health_view import (
    build_peer_table,
    get_metrics_snapshot,
    get_network_summary_dict,
)


def _html_page(rows: list[dict[str, Any]], summary: dict[str, Any]) -> bytes:
    body_rows = "".join(
        "<tr>"
        f"<td>{escape(str(row['peer_id']))}</td>"
        f"<td>{escape(str(row['connections']))}</td>"
        f"<td>{escape(str(row['score']))}</td>"
        f"<td>{escape(str(row['latency_ms']))}</td>"
        f"<td>{escape(str(row['success_rate']))}</td>"
        f"<td>{escape('yes' if row['protected'] else 'no')}</td>"
        f"<td>{escape(str(row['unhealthy']))}</td>"
        "</tr>"
        for row in rows
    )
    total_peers = escape(str(summary.get("total_peers", 0)))
    total_conns = escape(str(summary.get("total_connections", 0)))
    avg_health = escape(f"{float(summary.get('average_peer_health', 0.0)):.3f}")
    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<meta http-equiv="refresh" content="2"/>
<title>py-libp2p health</title>
<style>
body {{ font-family: sans-serif; margin: 1rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
th {{ background: #f0f0f0; }}
</style>
</head><body>
<h1>Connection health</h1>
<p>Peers: {total_peers} |
Connections: {total_conns} |
Avg health: {avg_health}</p>
<p><a href="/api/summary">JSON summary</a> |
<a href="/api/metrics">JSON metrics</a> |
<a href="/api/metrics?format=prometheus">Prometheus</a></p>
<table>
<tr><th>peer_id</th><th>conns</th><th>score</th><th>latency_ms</th>
<th>success</th><th>protected</th><th>unhealthy</th></tr>
{body_rows}
</table>
</body></html>"""
    return html.encode("utf-8")


def _make_handler(host: IHost) -> type[BaseHTTPRequestHandler]:
    class HealthHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                summary = get_network_summary_dict(host)
                rows = build_peer_table(host)
                payload = _html_page(rows, summary)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            if parsed.path == "/api/summary":
                data = json.dumps(get_network_summary_dict(host)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if parsed.path == "/api/metrics":
                params = parse_qs(parsed.query)
                fmt = params.get("format", ["json"])[0]
                if fmt not in ("json", "prometheus"):
                    fmt = "json"
                body = get_metrics_snapshot(host, fmt).encode("utf-8")
                ctype = (
                    "text/plain; version=0.0.4"
                    if fmt == "prometheus"
                    else "application/json"
                )
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(404)
            self.end_headers()

    return HealthHandler


async def run_health_web(
    host: IHost,
    *,
    host_addr: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Serve health HTML and JSON/Prometheus APIs until cancelled."""
    handler = _make_handler(host)
    server = ThreadingHTTPServer((host_addr, port), handler)

    async def serve() -> None:
        await trio.to_thread.run_sync(server.serve_forever)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(serve)
        print(f"Health web UI: http://{host_addr}:{port}/")
        try:
            await trio.sleep_forever()
        finally:
            server.shutdown()
