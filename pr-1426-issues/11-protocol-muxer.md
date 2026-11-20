# Protocol Muxer (multiselect) — Cancellation-Semantics Issue

## Summary

The multiselect client (`libp2p/protocol_muxer/multiselect_client.py`) uses `fail_after` for negotiation timeouts, raising `TooSlowError` which burns CPU in the event loop instead of cancelling silently.

## Issues

- **`fail_after` raises `TooSlowError`**: Protocol-negotiation timeouts propagate as exceptions that burn CPU instead of cancelling silently.

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
