# WebTransport Echo Demo

Runnable example: `webtransport_echo.py` — two peers over libp2p WebTransport
(HTTP/3 ALPN `h3` + Noise XX on the first client-opened stream).

## Run

From the repo root (with the package importable, e.g. `PYTHONPATH=.` or an editable install):

```bash
# Terminal A — listener (OS-chosen UDP port)
PYTHONUNBUFFERED=1 PYTHONPATH=. python3 ./examples/webtransport/webtransport_echo.py -p 0

# Terminal B — dialer (paste the printed multiaddr, including /certhash/ and /p2p/)
PYTHONUNBUFFERED=1 PYTHONPATH=. python3 ./examples/webtransport/webtransport_echo.py -d '<LISTEN_MULTIADDR>'
```

## Captured run (2026-09-08, after #1514 Chrome-compatible certs)

### Server (raw)

```
I am 16Uiu2HAmL2FfsJ8iiP5opAX3RpLEceWtMoUyU7vjEycapXjjoQKf
Listener ready, listening on:
/ip4/127.0.0.1/udp/42893/quic-v1/webtransport/certhash/uEiCZr8hiHvXySotMLJr_uBKd7gHDv3aLaBf9AxwWcavl3Q/certhash/uEiBB5LGyBOMiIcNwcXCqNifujc9x24JEEZptgRpU14_xyA/p2p/16Uiu2HAmL2FfsJ8iiP5opAX3RpLEceWtMoUyU7vjEycapXjjoQKf

Run this from the same folder in another console:

python3 ./examples/webtransport/webtransport_echo.py -d /ip4/127.0.0.1/udp/42893/quic-v1/webtransport/certhash/uEiCZr8hiHvXySotMLJr_uBKd7gHDv3aLaBf9AxwWcavl3Q/certhash/uEiBB5LGyBOMiIcNwcXCqNifujc9x24JEEZptgRpU14_xyA/p2p/16Uiu2HAmL2FfsJ8iiP5opAX3RpLEceWtMoUyU7vjEycapXjjoQKf

Waiting for inbound WebTransport (ALPN h3, CONNECT /.well-known/libp2p-webtransport?type=noise)...
2026-09-08 17:01:42,840 INFO [quic] [bbdce724f06a6e04] Negotiated protocol version 0x00000001 (VERSION_1)
2026-09-08 17:01:42,844 INFO [quic] [bbdce724f06a6e04] ALPN negotiated protocol h3
2026-09-08 17:01:43,090 INFO [quic] [bbdce724f06a6e04] Connection close received (code 0x0, reason )
```

### Client (raw)

```
I am 16Uiu2HAmEjeufNp2E8177GHHgZxwxBPuqpU1ShsDFpGBWoyq1SQh
STARTING CLIENT CONNECTION PROCESS
Dialing WebTransport multiaddr (expects /certhash/): /ip4/127.0.0.1/udp/42893/quic-v1/webtransport/certhash/uEiCZr8hiHvXySotMLJr_uBKd7gHDv3aLaBf9AxwWcavl3Q/certhash/uEiBB5LGyBOMiIcNwcXCqNifujc9x24JEEZptgRpU14_xyA/p2p/16Uiu2HAmL2FfsJ8iiP5opAX3RpLEceWtMoUyU7vjEycapXjjoQKf
2026-09-08 17:01:42,842 INFO [quic] [bbdce724f06a6e04] Negotiated protocol version 0x00000001 (VERSION_1)
2026-09-08 17:01:42,843 INFO [quic] [bbdce724f06a6e04] ALPN negotiated protocol h3
CLIENT CONNECTED TO SERVER
Sent: hi, there!

Got: hi, there!
```

## Annotated walkthrough

### ALPN `h3` vs `libp2p`

Native `quic-v1` negotiates ALPN **`libp2p`** — a distinct fingerprint for DPI.
WebTransport negotiates ALPN **`h3`** (see client log: `ALPN negotiated protocol h3`).
On the wire this looks like ordinary HTTP/3 / modern web traffic.

### WT CONNECT well-known path

After TLS, the dialer opens an HTTP/3 Extended CONNECT with
`:protocol = webtransport` (or draft-15 `webtransport-h3`) to:

```
/.well-known/libp2p-webtransport?type=noise
```

The listener prints that path in its “Waiting for inbound…” line. Session streams
are WebTransport streams under that CONNECT.

### Noise + certhash

Listen multiaddrs carry **two** `/certhash/<multibase-sha256>/` components
(current + next cert, **13-day** dual rotation, hard ceiling 14). The dialer must
use those hashes for TLS certificate binding. After CONNECT, the first
**client-opened** WT stream runs Noise XX; the server includes the
`webtransport_certhashes` extension so Peer ID is bound to the advertised
fingerprints.

### Chrome / `serverCertificateHashes` (#1514)

**Before this fix:** Chromium rejected the stock CN-only leaf (no X.509
extensions) even when `/certhash/` SHA-256 matched. Typical symptoms:

- Browser UI: `WebTransportError: Opening handshake failed`
- Host: `CERTIFICATE_VERIFY_FAILED` / `certificate unknown`, then timeout
  waiting for WT session / Noise

**After this fix:** leaves mirror go-libp2p `generateCert`:

| Field            | Value                                      |
| ---------------- | ------------------------------------------ |
| Subject          | empty                                      |
| BasicConstraints | CA=true (critical)                         |
| KeyUsage         | digitalSignature \| keyCertSign (critical) |
| ExtKeyUsage      | serverAuth \| clientAuth                   |
| Validity         | default **13 days** (≤14 W3C ceiling)      |

Unit tests assert these fields. Quick local check of a minted leaf:

```
subject_empty: True
basic_constraints_ca: True critical: True
key_usage_ds_kcs: True True critical: True
eku: serverAuth, clientAuth
window_days: 13.0
```

**Manual Chromium checklist** (secure context required — `https:` or
`http://localhost` / `127.0.0.1`):

1. Start a py-libp2p listener with `enable_webtransport=True` and note the
   listen multiaddr `/certhash/` digests.
1. Build `serverCertificateHashes` from the SHA-256 of the presented DER
   (same digest encoded in `/certhash/`).
1. In Chromium: `const wt = new WebTransport(url, { serverCertificateHashes }); await wt.ready;`
1. Expect `ready` to resolve (no `Opening handshake failed`), then complete
   js-libp2p Noise + an application stream.

Prefer Chromium; Firefox WebTransport pinning differs and may not accept this
path. A full Stage/js-libp2p browser capture can be pasted into a PR comment
when available; py↔py echo above proves the listen path still works after the
cert change.

### Censorship story

Same camouflage *class* as Mullvad-style QUIC/HTTP/3 traffic: monitors see
`h3`, not ALPN `libp2p`. Residual risks remain (well-known path fingerprinting,
cert properties, timing, blocking all HTTP/3). This is not MASQUE/VPN tunneling.

### TLS + Noise double encryption

One-liner: **HTTP/3 TLS encrypts the session; Noise authenticates libp2p Peer ID
— both are required by the WebTransport spec (do not drop Noise).**

### Failure case (bad certhash)

If you dial with a wrong or stripped `/certhash/`, TLS hash verification or the
Noise `webtransport_certhashes` subset check fails and the connection aborts
before echo. Example: replace a certhash component with another peer’s hash and
re-run the client — expect a handshake / dial error instead of `Got: hi, there!`.
