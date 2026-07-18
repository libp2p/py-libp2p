#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import re

PROM_PATH = Path(__file__).parent / "prometheus.yml"


def set_exporter_port(port: int) -> None:
    content = PROM_PATH.read_text()
    pattern = r"host\\.docker\\.internal:\\d+"
    replacement = f"host.docker.internal:{port}"
    new = re.sub(pattern, replacement, content)
    PROM_PATH.write_text(new)
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
