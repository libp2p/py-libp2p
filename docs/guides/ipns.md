# IPNS — Mutable Names over Immutable CIDs

This guide explains IPNS (InterPlanetary Name System): what it is, how to use it with
`py-ipfs-lite`, and — critically — the trust model that backs it. The trust model section
is the most important part; understanding it will give you confidence in the security
properties of any system you build on top of IPNS.

**Relevant examples:**

- [`examples/15_ipns_mutable_registry.py`](../../examples/15_ipns_mutable_registry.py) —
  publish and resolve a mutable pointer (your entry point)
- [`examples/18_ipns_trust_boundary.py`](../../examples/18_ipns_trust_boundary.py) —
  adversarial demo showing forged record rejection (the flagship security demo)

**Run them:**

```bash
uv run python examples/15_ipns_mutable_registry.py
uv run python examples/18_ipns_trust_boundary.py
```

---

## What IPNS Is For

IPFS content is immutable by design: a CID is a cryptographic hash of the data it refers
to. If the data changes, the CID changes. This is the property that makes content
verification reliable — but it creates a problem for anything that needs to evolve over
time. If you publish a versioned agent registry, a dataset, or a model checkpoint, the
CID of the latest version changes with every update. Consumers who have the old CID will
not automatically find the new one.

**IPNS solves this with a layer of indirection.** An IPNS name is a stable identifier —
specifically, a libp2p `PeerID` — that can be updated to point to a new CID at any time.
The mapping from name to CID is stored in the DHT and is signed by the name owner's
private key, so consumers can verify that the current value is authentic without trusting
any intermediary.

```
IPNS Name (stable, never changes)          Current value (changes with each publish)
───────────────────────────────────        ─────────────────────────────────────────
12D3KooWHNte...  ──────────────────────►  /ipfs/bafyrei...v1   (version 1.0.0)
                                           ▼ (after update)
12D3KooWHNte...  ──────────────────────►  /ipfs/bafyrei...v2   (version 2.0.0)
```

The canonical use case for AI Agent: publish the IPNS name of your agent registry
once (in your README, in your grant application, in your config file). Every time you
add agents or update the registry, call `publish_name()` with the new CID. Consumers
always resolve the same IPNS name to get the latest state.

---

## Sequence Numbers

IPNS records include a `sequence` field to prevent replay attacks. A consumer will only
accept a record with a sequence number higher than the last one they saw.

`py-ipfs-lite` uses **the current Unix timestamp** as the sequence number. This means:

- Each `publish_name()` call generates a strictly increasing sequence number (as long as
  the system clock moves forward).
- You cannot publish twice within the same second and have the second publish "win" in the
  DHT — both will have the same sequence and the outcome is DHT-implementation dependent.
- After a node restart, the sequence continues from the current timestamp, so old records
  will always be superseded by new publishes.

This is a pragmatic choice that avoids needing to persist a monotonic counter across
restarts. The trade-off is that the sequence number carries no semantic meaning beyond
"this record is newer than records with a lower value."

---

## Example 15: Mutable Pointer — Your Entry Point

[`examples/15_ipns_mutable_registry.py`](../../examples/15_ipns_mutable_registry.py)

This example demonstrates the full publish → update → resolve lifecycle using a versioned
agent registry as the payload.

### Publishing a name

```python
import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    peer = Peer(
        Config(reprovide_interval_seconds=-1, blockstore_type="memory"),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await peer.start()

    # Create the initial registry DAG
    v1_cid = await peer.add_node(
        {"version": "1.0.0", "agents": ["summarizer", "classifier"]},
        codec="dag-cbor"
    )
    print(f"Created Registry v1 DAG: {v1_cid}")

    # The IPNS name is always this peer's own PeerID
    name = str(peer.host.id())

    # Publish: DHT key /ipns/{peerID} → signed record pointing to /ipfs/{v1_cid}
    await peer.publish_name(f"/ipfs/{v1_cid}")
    print(f"IPNS name: {name}  →  /ipfs/{v1_cid}")
```

`publish_name()` takes any string value — by convention, IPFS paths use `/ipfs/{cid}`,
but you can store any string (a URL, a JSON blob, an agent name). The value is signed
with this peer's private key before being written to the DHT.

### Updating to a new version

```python
    # The registry grows — a new CID is produced
    v2_cid = await peer.add_node(
        {"version": "2.0.0", "agents": ["summarizer", "classifier", "retriever"]},
        codec="dag-cbor"
    )

    # Publish again — same IPNS name, different CID, higher sequence number
    await peer.publish_name(f"/ipfs/{v2_cid}")
    print("Name updated — same name, new CID")
```

### Resolving the name

```python
    # Resolve by PeerID string — fetches from DHT, verifies signature
    resolved = await peer.resolve_name(name)
    print(f"Resolved: {resolved}")   # "/ipfs/bafyrei...v2"

    # Extract the CID and fetch the actual content
    resolved_cid = resolved.replace("/ipfs/", "")
    assert resolved_cid == v2_cid   # always the latest publish

    registry = await peer.get_node(resolved_cid)
    print(f"Registry: {registry}")
    # {"version": "2.0.0", "agents": ["summarizer", "classifier", "retriever"]}

    await peer.close()

trio.run(main)
```

`resolve_name()` does two things: it fetches the record from the DHT and then runs the
full cryptographic validation chain before returning the value. A record that fails
validation is never returned — it raises `RoutingError` instead.

---

## Example 18: Trust Model — The Flagship Security Demo

[`examples/18_ipns_trust_boundary.py`](../../examples/18_ipns_trust_boundary.py)

This is the most important example in this guide from a security standpoint. It
demonstrates concretely that `py-ipfs-lite` cannot be fooled into accepting a forged IPNS
record, even when the attacker attempts two distinct strategies.

Understanding this demo will give you confidence in any system that relies on IPNS for
authoritative name resolution.

### The attack scenario

```
DHT (untrusted network)
        │
        │  attacker PUT /ipns/{publisher_peer_id} → forged_record
        │  (attacker does not have publisher's private key)
        ▼
Consumer calls peer.resolve_name(publisher_peer_id)
        │
        ▼
validate_ipns_record() ← does this catch the forgery?
```

The DHT is treated as a hostile network: any peer can PUT any bytes at any key. The
IPNS trust model's job is to ensure that even if a malicious peer injects a forged record
at the right DHT key, consumers will reject it.

### Strategy 1: Sign with attacker's own key

The attacker creates a valid IPNS record (correct format, correct signature) but signs
it with their own private key, not the publisher's.

```python
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from py_ipfs_lite.ipns import create_ipns_record, validate_ipns_record

# Publisher's identity
publisher_keypair = create_new_key_pair()
publisher_id = ID.from_pubkey(publisher_keypair.public_key)

# Authentic record — publisher signs their own record
authentic_val = "/ipfs/bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
authentic_record = create_ipns_record(publisher_keypair.private_key, authentic_val, sequence=1)

# Validate: passes ✅
validate_ipns_record(authentic_record, publisher_id)

# Attacker's identity
attacker_keypair = create_new_key_pair()
malicious_val = "/ipfs/bafybeihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"

# Forged record — attacker signs with their own key
forged_record = create_ipns_record(attacker_keypair.private_key, malicious_val, sequence=2)

# Validate against publisher's PeerID: FAILS ✅
try:
    validate_ipns_record(forged_record, publisher_id)
except RoutingError as e:
    print(f"Correctly rejected: {e}")
    # "IPNS record pubKey does not match the expected Peer ID"
```

**Why it fails:** The embedded `pubKey` in the forged record hashes to the attacker's
`PeerID`, not the publisher's. `validate_ipns_record()` computes
`ID.from_pubkey(embedded_pubkey)` and compares it to `publisher_id`. They do not match.

### Strategy 2: Embed the publisher's public key, sign with attacker's key

A more sophisticated attack: the attacker takes the forged record from Strategy 1 and
replaces the embedded `pubKey` field with the publisher's actual public key, hoping that
the validator will use the embedded key to verify the signature without checking whether
the key matches the expected PeerID.

```python
from libp2p.records.pb.ipns_pb2 import IpnsEntry

# Attacker replaces the embedded pubKey with the publisher's pubKey
sneaky_entry = IpnsEntry()
sneaky_entry.ParseFromString(forged_record)
sneaky_entry.pubKey = publisher_keypair.public_key.serialize()  # publisher's key
sneaky_forged = sneaky_entry.SerializeToString()

# Validate: FAILS ✅
try:
    validate_ipns_record(sneaky_forged, publisher_id)
except RoutingError as e:
    print(f"Correctly rejected: {e}")
    # "IPNS V2 signature is invalid"
```

**Why it fails:** The V2 signature was computed over the CBOR payload using the
*attacker's* private key. When `validate_ipns_record()` extracts the publisher's public
key (correctly, because it now matches the expected PeerID) and tries to verify the V2
signature with it, the verification fails. The signature was made by a different private
key than the one whose public key is now embedded in the record.

### The full output when you run example 18

```
--- IPNS Trust Boundary Demo ---

[Publisher] Identity generated: 12D3KooW...
[Publisher] Creating authentic record targeting: /ipfs/bafybe...
[Consumer] Validating authentic record against Publisher's Peer ID...
✅ [Consumer] Authentic record accepted!

[Attacker] Identity generated: 12D3KooW...
[Attacker] Attempting to forge record targeting malicious payload: /ipfs/bafybei...
[Attacker] Strategy: Sign malicious payload with attacker key, but inject it into DHT under publisher's routing key.

[Consumer] Receiving forged record 1 (Attacker's pubkey embedded)...
✅ [Consumer] Forged record correctly rejected: IPNS record pubKey does not match the expected Peer ID

[Consumer] Receiving forged record 2 (Publisher's pubkey embedded, invalid signature)...
✅ [Consumer] Forged record correctly rejected: IPNS V2 signature is invalid
```

Both attack strategies fail independently. Even if the attacker somehow knew the
publisher's public key (which is public information), they still cannot forge a valid
record without the publisher's *private* key.

---

## Trust Model Summary

| Property | Guaranteed? | How |
|---|---|---|
| Record was signed by the named peer | ✅ Yes | Ed25519 signature verification |
| Record has not been tampered with | ✅ Yes | V2 signature covers the CBOR payload; value/validity must match |
| Record is not expired | ✅ Yes | Validity timestamp checked against UTC now |
| A forged record is rejected even if the attacker knows the public key | ✅ Yes | Signature check with publisher's key will fail on attacker-signed data |
| IPNI announcement is authenticated | ❌ No | IPNI `PUT /routing/v1/providers/{cid}` is unauthenticated by protocol — any peer can announce any CID |
| DHT peer identity for stored records | ❌ Not by DHT | Any peer can PUT any bytes at any DHT key — the signature check is what closes this gap |

The bottom line: `resolve_name()` is safe to use as an authoritative lookup in a security
context. The only trust assumption it makes is that the caller knows the correct `PeerID`
to look up — which is typically a hard-coded or out-of-band-distributed value.

---

## API Reference

### `await peer.publish_name(value, lifetime_hours=24)`

Signs and publishes an IPNS record mapping this peer's `PeerID` to `value`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `value` | `str` | — | The value to publish (e.g., `/ipfs/{cid}`) |
| `lifetime_hours` | `int` | `24` | How long the record is valid before expiry |
| **Returns** | `str` | — | This peer's `PeerID` as a base58 string (the IPNS name) |

### `await peer.resolve_name(peer_id_str)`

Fetches and cryptographically validates the IPNS record for `peer_id_str` from the DHT.

| Parameter | Type | Description |
|---|---|---|
| `peer_id_str` | `str` | The `PeerID` to resolve (base58 string) |
| **Returns** | `str` | The validated value stored in the record |
| **Raises** | `RoutingError` | If the record cannot be found, has an invalid signature, or has expired |

### Low-level functions (in `py_ipfs_lite/ipns.py`)

If you need direct access to record creation and validation without a live `Peer`:

```python
from py_ipfs_lite.ipns import create_ipns_record, validate_ipns_record

# Create a signed record (returns raw bytes)
record_bytes = create_ipns_record(private_key, value, sequence, lifetime_hours=24)

# Validate a record against an expected PeerID
entry = validate_ipns_record(record_bytes, expected_peer_id)
# Returns the parsed IpnsEntry on success, raises RoutingError on failure
```

These are the same functions used internally by `publish_name()` and `resolve_name()`,
and are available directly for testing, auditing, or building custom IPNS workflows.
