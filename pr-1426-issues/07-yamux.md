# Yamux Stream Muxer — Read Semantics & Bookkeeping-Leak Issues

## Summary

The yamux stream muxer (`libp2p/stream_muxer/yamux/`) blocks readers waiting for EOF, leaks bookkeeping for fully-closed streams with unread buffered data, and can double-release the backlog semaphore slot.

## Issues

- **`read()` blocks waiting for EOF**: Reads wait for stream close instead of returning available data, causing deadlocks where the reader blocks on close while the writer blocks on the reader.
- **Bookkeeping leak for closed streams**: Fully-closed streams holding unread buffered data are never reclaimed.
- **Backlog slot can be double-released**: Close/reset from both sides can release the connection's backlog semaphore slot twice.

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
