# WebTransport Echo Demo

Runnable example: `webtransport_echo.py` — two peers over libp2p WebTransport
(HTTP/3 ALPN `h3` + Noise XX on the first client-opened stream).

## Run

From the repo root (with the package importable, e.g. `PYTHONPATH=.` or an editable install):

```bash
# Terminal A — listener (OS-chosen UDP port)
python3 ./examples/webtransport/webtransport_echo.py -p 0

# Terminal B — dialer (paste the printed multiaddr, including /certhash/ and /p2p/)
python3 ./examples/webtransport/webtransport_echo.py -d '<LISTEN_MULTIADDR>'
```

## Captured run (2026-09-08)

### Server (raw)

```
I am 16Uiu2HAm765pEhEgJJmz5xHLt8Ay2a16qtS9uPzjUGjuCKTAtQYN
Listener ready, listening on:
/ip4/127.0.0.1/udp/60121/quic-v1/webtransport/certhash/uEiCiRK0Leo5nW1Cj2J9qR1_64ioG97vcEhXpf1N6-BbsZQ/certhash/uEiB-f4XceoM13E6F0jyzhSANgQP43pIh6lAU0dx4JKI0Ew/p2p/16Uiu2HAm765pEhEgJJmz5xHLt8Ay2a16qtS9uPzjUGjuCKTAtQYN

Run this from the same folder in another console:

python3 ./examples/webtransport/webtransport_echo.py -d /ip4/127.0.0.1/udp/60121/quic-v1/webtransport/certhash/uEiCiRK0Leo5nW1Cj2J9qR1_64ioG97vcEhXpf1N6-BbsZQ/certhash/uEiB-f4XceoM13E6F0jyzhSANgQP43pIh6lAU0dx4JKI0Ew/p2p/16Uiu2HAm765pEhEgJJmz5xHLt8Ay2a16qtS9uPzjUGjuCKTAtQYN

Waiting for inbound WebTransport (ALPN h3, CONNECT /.well-known/libp2p-webtransport?type=noise)...
2026-09-08 03:37:58,409 INFO [quic] [9b5ff8c4eb491ec6] Negotiated protocol version 0x00000001 (VERSION_1)
2026-09-08 03:37:58,411 INFO [quic] [9b5ff8c4eb491ec6] ALPN negotiated protocol h3
2026-09-08 03:37:58,658 INFO [quic] [9b5ff8c4eb491ec6] Connection close received (code 0x0, reason )
```

### Client (raw)

```
I am 16Uiu2HAkyfVeK1wARrrgCUkEfohLpDcW34TkXc7r426vGcRhy3h2
STARTING CLIENT CONNECTION PROCESS
Dialing WebTransport multiaddr (expects /certhash/): /ip4/127.0.0.1/udp/60121/quic-v1/webtransport/certhash/uEiCiRK0Leo5nW1Cj2J9qR1_64ioG97vcEhXpf1N6-BbsZQ/certhash/uEiB-f4XceoM13E6F0jyzhSANgQP43pIh6lAU0dx4JKI0Ew/p2p/16Uiu2HAm765pEhEgJJmz5xHLt8Ay2a16qtS9uPzjUGjuCKTAtQYN
2026-09-08 03:37:58,410 INFO [quic] [9b5ff8c4eb491ec6] Negotiated protocol version 0x00000001 (VERSION_1)
2026-09-08 03:37:58,410 INFO [quic] [9b5ff8c4eb491ec6] ALPN negotiated protocol h3
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
(current + next cert, ≤14-day dual rotation). The dialer must use those hashes
for TLS certificate binding. After CONNECT, the first **client-opened** WT stream
runs Noise XX; the server includes the `webtransport_certhashes` extension so
Peer ID is bound to the advertised fingerprints.

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
