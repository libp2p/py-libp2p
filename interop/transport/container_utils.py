"""Portable container IP discovery.

hostname -I is GNU/Linux-only (not macOS, BSD, Alpine). This module
uses the UDP connect trick as the primary method, with hostname -I
as a Linux-specific fallback only.
"""
from __future__ import annotations

import socket
import subprocess


def get_container_ip() -> str:
    """Return the primary outbound IP of this container/host."""
    # UDP connect: no packet is sent, works on every POSIX OS
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass

    # Linux/Docker fallback only
    try:
        result = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split()[0]
    except (OSError, subprocess.SubprocessError):
        pass

    return "172.17.0.1"  # Docker default bridge fallback
