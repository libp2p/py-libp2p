# Discovery / Random Walk — Query-Storm & Refresh-Tuning Issues

## Summary

The random-walk discovery (`libp2p/discovery/random_walk/`) causes startup query storms and leaves connections behind after walks: concurrency is too high, the refresh interval too short, and post-walk connections are not pruned.

## Issues

- **Startup query storms**: High random-walk concurrency (10) floods peers with queries at startup.
- **Refresh interval too short**: Routing-table refresh runs every 60s, causing periodic query bursts.
- **Post-walk connections not pruned**: Connections opened by a random walk are left open afterwards.
- **Redundant post-walk trim in RTRefreshManager**: Duplicate connection-trim logic.
- **Verbose timing comments** clutter the configuration.

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
