# Host (basic_host, identify, ping) — Cancellation & Backoff Issues

## Summary

The host layer (`libp2p/host/basic_host.py`, `libp2p/host/ping.py`) burns CPU through `TooSlowError` from `fail_after`, leaks cancelled tasks in `new_stream`/`send_command`, has no identify backoff (causing cancellation storms), crashes with `UnboundLocalError`, and leaks ping streams.

## Issues

- **`fail_after` raises `TooSlowError`**: Timeouts propagate as exceptions that burn CPU in the event loop instead of cancelling silently.
- **Cancellation leak in `new_stream` / `send_command`**: Cancelled operations leave tasks/streams behind.
- **No identify backoff on `new_stream` failure**: Backoff applies only on read timeout, not when opening the stream fails.
- **No per-peer identify backoff**: Repeated identify attempts to the same peer cause cancellation storms.
- **`UnboundLocalError` crash in identify**: A code path references an unbound local variable.
- **Ping streams leak**: Ping streams are not closed after completion or reset on error.

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
