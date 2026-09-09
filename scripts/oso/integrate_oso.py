#!/usr/bin/env python3
"""Entry wrapper for the productized OSO module."""

from __future__ import annotations

from libp2p.observability.oso.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
