#!/usr/bin/env python3
"""Collect and persist py-libp2p OSO health metrics."""

from __future__ import annotations

from libp2p.observability.oso.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
