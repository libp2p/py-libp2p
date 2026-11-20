# PubSub — Peer Registration & Stream-Lifecycle Issues

## Summary

The pubsub implementation (`libp2p/pubsub/pubsub.py`) silently leaves peers unregistered when the `connected` notifee fires before the muxer handshake completes, does not re-establish dead streams, and offers no way to register a peer whose connection was established out-of-band.

## Issues

- **Peer registration is one-shot**: A single `new_stream` attempt fails if the `connected` notifee fires before the handshake completes, leaving the peer silently unregistered.
- **No registration retry**: There is no retry with backoff while the peer remains connected.
- **Dead streams not re-established**: Streams to registered peers are not reopened when they die.
- **No public `ensure_peer_stream` API**: Peers connected out-of-band (e.g. via `connect_peer` reusing an existing mDNS connection) never fire a `connected` notifee and can never be registered.

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
