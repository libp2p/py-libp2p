# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in `py-ipfs-lite`, please **do not** open a public issue.

Instead, please report it via GitHub Security Advisories for this repository, or email the maintainer directly. We will investigate all reports promptly.

## Supported Versions

| Version  | Supported          |
| -------- | ------------------ |
| `main`   | :white_check_mark: |
| \< 0.1.0 | :x:                |

## Current Trust Model

Before reporting a vulnerability, please review our documented trust model:

1. **IPNS Resolve is Verified**: `resolve_name()` verifies the Ed25519 V2 signature, checks that the embedded pubkey matches the expected PeerID, and verifies the record has not expired.
1. **IPNI Announce is Unauthenticated**: IPNI `provide()` is a no-op because the protocol requires Reframe or signed provider records. Anyone can announce a CID, but block integrity is always verified on fetch.
1. **Transport Security is Noise-Only**: SECIO is fully removed from the upstream stack. All connections use Noise (XX pattern) for transport layer encryption and authentication.
1. **HTTP API is Unauthenticated**: The daemon's HTTP API (`--api-port 5001`) has no built-in auth. It binds to `127.0.0.1` by default and should never be exposed to the public internet without a reverse proxy.

For more details, see the [Production Deployment Guide](docs/guides/production-deployment.md#security-notes).
