# QUIC Transport — Memory, Socket & CPU Efficiency Issues

## Summary

The QUIC transport (`libp2p/transport/quic/`) suffers from resource leaks and CPU inefficiency: connection objects and registry entries leak, UDP sockets and background tasks are not closed on dial failure/cancellation, and the event-processing loop busy-spins.

## Issues

### Memory Leaks

- **ServerQuicConnection leaks**: Connections leak in the registry and listener tracking.
- **Registry CIDs not purged on disconnect**: Connection IDs are not unregistered/purged when a connection disconnects.
- **Multiple major memory leaks**: At least four distinct leak sources exist across connection/registry/listener paths.
- **`get_all_cids_for_connection` is O(n)**: Linear scans instead of O(1) lookups.

### Socket / FD Leaks

- **UDP socket not closed on dial cancellation/failure**: Dial failures leak file descriptors.
- **`close()` does not guarantee socket close**: Socket close and background-task cancellation are not guaranteed.
- **`_handle_connection_terminated` leaves sockets open**: UDP socket and background task scopes not closed.
- **Failed/cancelled dials leak tasks and sockets**: Background tasks survive failed dials.

### CPU / Event Loop

- **Event loop busy-spins**: The processing loop spins at 100% CPU waiting for events.
- **2s delay when `timer <= now`**: Expired timers wait for the full poll interval.
- **No idle sleep**: The loop does not sleep when idle.
- **Aggressive idle polling**: Idle poll interval too short; no activity signaling on stream write.

### Cleanup

- **Temporary CONN_CLOSE_TRACE stack logging** left in the code.
- **DEBUG log level forced at import time**.
- **Syntax error in an except block**.

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
