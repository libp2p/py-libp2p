# py-libp2p WebRTC Demo Scripts

Two complete terminal demos showing py-libp2p's WebRTC transport working end-to-end.

______________________________________________________________________

## Demo 1 — WebRTC-Direct (Private → Public)

Direct UDP connection. No relay. Client dials a known server.

```
[private_peer.py]  ──UDP/DTLS/SCTP──>  [public_peer.py]
        aiortc on both sides; ICE + DTLS handshake; then Yamux streams
```

### Run it

```bash
# Terminal 1
python examples/chat_webrtc/webrtc-direct/private_peer.py

# Terminal 2 (after server prints its address)
python examples/chat_webrtc/webrtc-direct/public_peer.py
# or explicit addr:
python examples/chat_webrtc/webrtc-direct/public_peer.py  /ip4/127.0.0.1/udp/54921/webrtc-direct/certhash/uEi../<peer_id>
```

**What the scripts do:**

| Script | Key call                                                             | Source template                                                 |
| ------ | -------------------------------------------------------------------- | --------------------------------------------------------------- |
| server | `WebRTCDirectTransport` → `create_listener` → `listener.listen(...)` | `setup_server_peer()` in `test_webrtc_pvt_to_public_example.py` |
| client | `WebRTCDirectTransport` → `transport.dial(server_maddr)`             | `setup_client_peer()` in `test_webrtc_pvt_to_public_example.py` |

Server writes its multiaddr to `webrtc_direct_addr.json`. Client reads it automatically.

______________________________________________________________________

## Demo 2 — WebRTC Private-to-Private via Circuit Relay

Both peers are behind NAT (simulated). They find each other through a relay,
exchange SDP via the relay stream, then attempt a direct UDP connection via ICE.

```
[Alice]  ──TCP──>  [Relay]  <──TCP──  [Bob]
   │                                     │
   └──── SDP via /webrtc-signaling ──────┘   (over relay circuit)
   └═══════════ direct UDP (ICE) ═════════╝   (after handshake)
```

### Run it

```bash
# Terminal 1 — start relay first
python examples/chat_webrtc/webrtc-pvt-to-pvt/relay.py

# Terminal 2 — Alice listens (after relay is up)
python examples/chat_webrtc/webrtc-pvt-to-pvt/peer_node.py --mode listen

# Terminal 3 — Bob dials (after Alice is up)
python examples/chat_webrtc/webrtc-pvt-to-pvt/peer_node.py --mode dial
```

**What the scripts do:**

| Script | Key calls                                                                | Source template                                               |
| ------ | ------------------------------------------------------------------------ | ------------------------------------------------------------- |
| relay  | `CircuitV2Protocol(allow_hop=True)`                                      | `setup_relay_server()` in `test_webrtc_pvt_to_pvt_example.py` |
| Alice  | `WebRTCTransport.start()` → `ensure_listener_ready()` → writes addr file | `setup_nat_peer()` + `WebRTCTransport` in pvt-to-pvt test     |
| Bob    | `WebRTCTransport.start()` → `transport.dial(alice_webrtc_maddr)`         | `initiate_connection()` flow in `transport.py`                |

**Address files (auto-created/deleted):**

```
relay_addr.json        ← relay writes this; Alice + Bob read it
alice_webrtc_addr.json ← Alice writes this; Bob reads it
```

**Alice's WebRTC address format** (what Bob dials):

```
/ip4/127.0.0.1/tcp/9091/p2p/<relay-id>/p2p-circuit/webrtc/p2p/<alice-id>
```

______________________________________________________________________

## What Each Transport Does Internally

### WebRTC-Direct (`WebRTCDirectTransport`)

- Generates an ECDSA certificate + `ufrag`/`ice-pwd` encoded in the multiaddr's `/certhash/` component
- Server encodes its fingerprint in the multiaddr so clients can verify DTLS without a CA
- UDP-only; no TCP relay needed; ICE does the NAT work

### WebRTC Private-to-Private (`WebRTCTransport`)

- Requires `CircuitV2Protocol` relay to exchange SDP (since both peers are "private")
- `ensure_listener_ready()` makes a relay reservation → relay gives peer a circuit slot
- `transport.dial()` opens a `/webrtc-signaling/0.0.1` stream over the circuit relay,
  exchanges offer/answer + ICE candidates, then tries direct UDP (hole-punching)
- After ICE succeeds: traffic is direct UDP, relay is no longer in the path

______________________________________________________________________

## Files Modified / Created by the Demos

```
relay_addr.json          created by webrtc_p2p_relay.py    deleted on Ctrl+C
alice_webrtc_addr.json   created by webrtc_p2p_peer.py -m listen   deleted on Ctrl+C
webrtc_direct_addr.json  created by webrtc_direct_server.py         deleted on Ctrl+C
```
