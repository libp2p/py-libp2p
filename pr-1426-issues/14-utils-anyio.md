# Utils & AnyIO Service — Address Handling & Task-Cancellation Issues

## Summary

The utility modules (`libp2p/utils/address_validation.py`, `libp2p/tools/anyio_service/tasks.py`) lack IPv6/relay-address handling helpers and have a task-cancellation bug: cancelling a task before it enters its cancel scope hangs forever in `wait_done()`.

## Issues

### utils / address_validation

- **No IPv6 availability detection**: No cached probe of whether the OS has usable IPv6.
- **No relay-address detection**: No helper to identify relay addresses (needed by the auto-connector to skip them).
- **No routability check**: No shared helper to reject loopback/link-local/private/multicast addresses while allowing CGNAT ranges.
- **Loopback IPv6 disallowed when host has no public IPv6**: Local loopback IPv6 peers are rejected on hosts without public IPv6.

### tools / anyio_service

- **`cancel()` before scope entry hangs**: Calling `cancel()` on a task that has not yet entered its cancel scope makes `wait_done()` wait forever, because the task can never finish on its own.

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
