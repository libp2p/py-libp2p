#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import re

PROM_PATH = Path(__file__).parent / "prometheus.yml"


def set_exporter_port(port: int) -> None:
    content = PROM_PATH.read_text()
    # Update py-libp2p target port (host.docker.internal or legacy 172.17.0.1)
    for pattern, replacement in [
        (r"host\.docker\.internal:\d+", f"host.docker.internal:{port}"),
        (r"172\.17\.0\.1:\d+", f"172.17.0.1:{port}"),
    ]:
        content = re.sub(pattern, replacement, content)
    PROM_PATH.write_text(content)
    print(f"Updated Prometheus target to host.docker.internal:{port}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("DEMO_EXPORTER_PORT", "8000")),
    )
    args = parser.parse_args()
    set_exporter_port(args.port)


if __name__ == "__main__":
    main()
