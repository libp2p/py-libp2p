# mDNS Spec Compliance Analysis - Round 2

Deep analysis comparing py-libp2p mDNS implementation against the
[libp2p mDNS spec](https://github.com/libp2p/specs/blob/master/discovery/mdns.md)
and [go-libp2p reference implementation](https://github.com/libp2p/go-libp2p/blob/master/p2p/discovery/mdns/mdns.go).

## Spec Requirements Checklist

### 1. Service Name Format

| Item | Spec | py-libp2p | go-libp2p | Status |
|------|------|-----------|-----------|--------|
| Default service type | `_p2p._udp.local` | `_p2p._udp.local.` | `_p2p._udp` | ✅ |
| Private network type | `_p2p-X._udp.local` | `_p2p-{fp}._udp.local.` | N/A in mdns.go | ✅ |
| Trailing dot | Standard DNS FQDN | Present | Absent (zeroconf adds) | ✅ |

**Verdict**: COMPLIANT. The trailing dot is standard DNS notation. Zeroconf handles
the difference transparently.

### 2. Peer Name (peer-name)

| Item | Spec | py-libp2p | go-libp2p | Status |
|------|------|-----------|-----------|--------|
| Random generation | "SHOULD generate random" | `stringGen(63)` | `randomString(32 + rand.Intn(32))` | ✅ |
| Lowercase alphanumeric | Required | `ascii_lowercase + digits` | `abcdefghijklmnopqrstuvwxyz0123456789` | ✅ |
| Length | >= 32, < 64 chars | 63 (fixed) | 32-63 (random) | ✅ |
| Not Peer ID | "SHOULD NOT use Peer ID" | Random string | Random string | ✅ |

**Verdict**: COMPLIANT. Both implementations follow the spec.

### 3. TXT Record Format (dnsaddr)

| Item | Spec | py-libp2p | go-libp2p | Status |
|------|------|-----------|-----------|--------|
| Format | `dnsaddr=/.../p2p/QmId` | `/ip4/{ip}/tcp/{port}/p2p/{id}` | `dnsaddr=` + multiaddr | ✅ |
| Multiple records | "Multiple allowed" | `dnsaddr`, `dnsaddr2`, ... | `[]string` TXTs array | ✅ |
| Peer ID in addr | Example shows it | Included | Included | ✅ |

**Spec Example**:
```
<peer-name>._p2p._udp.local IN TXT dnsaddr=/ip6/2001:DB8::.../tcp/4001/p2p/id
<peer-name>._p2p._udp.local IN TXT dnsaddr=/ip4/192.0.2.0/tcp/4001/p2p/id
```

**py-libp2p** (`broadcaster.py:111-117`):
```python
for i, addr in enumerate(multiaddrs):
    if i == 0:
        properties[b"dnsaddr"] = addr.encode()
    else:
        properties[f"dnsaddr{i + 1}".encode()] = addr.encode()
```

**go-libp2p**:
```go
var txts []string
for _, addr := range addrs {
    txts = append(txts, dnsaddrPrefix+addr.String())
}
```

**Verdict**: COMPLIANT. Both produce spec-compliant dnsaddr TXT records.

### 4. DNS-SD Meta Query

| Item | Spec | py-libp2p | go-libp2p | Status |
|------|------|-----------|-----------|--------|
| Query type | `_services._dns-sd._udp.local PTR` | `META_QUERY_TYPE = "_services._dns-sd._udp.local."` | Handled by zeroconf | ✅ |
| Response | `_services._dns-sd._udp.local PTR <service-name>` | Via ServiceBrowser | Via zeroconf browse | ✅ |

**Verdict**: COMPLIANT. Meta query support is implemented.

### 5. Private Network Support

| Item | Spec | py-libp2p | go-libp2p | Status |
|------|------|-----------|-----------|--------|
| Service type | `_p2p-X._udp.local` | `f"_p2p-{fp}._udp.local."` | Not in mdns.go (handled elsewhere) | ✅ |
| Fingerprint format | Base-16 (hex) | Passed through | N/A | ✅ |

**Verdict**: COMPLIANT.

### 6. Self-Discovery Filtering

| Item | Spec | py-libp2p | go-libp2p | Status |
|------|------|-----------|-----------|--------|
| Respond to own query | "peer must respond to own query" | Registers service | Registers service | ✅ |
| Filter own discoveries | Implicit | `if name == self.service_name: return` | `if info.ID == s.host.ID() { continue }` | ✅ |

**Analysis**:
- **Spec**: "a peer must respond to its own query. This allows other peers to passively discover it."
- **py-libp2p**: Filters by service name (unique per peer). Since each peer has a unique random service name, this is equivalent to filtering by peer ID.
- **go-libp2p**: Filters by peer ID after parsing TXT records.

**Verdict**: COMPLIANT. Both correctly filter self-discoveries.

### 7. Response Structure (PTR, TXT, SRV, A, AAAA)

| Item | Spec | py-libp2p | go-libp2p | Status |
|------|------|-----------|-----------|--------|
| PTR record | `<service> PTR <peer-name>.<service>` | Via zeroconf | Via zeroconf | ✅ |
| TXT record | `<peer-name>.<service> TXT dnsaddr=...` | Via zeroconf | Via zeroconf | ✅ |
| SRV record | `<peer-name>.<service> SRV ... <host>` | Via zeroconf | Via zeroconf | ✅ |
| A record | `<host> A <ipv4>` | Via zeroconf | Via zeroconf | ✅ |
| AAAA record | `<host> AAAA <ipv6>` | Via zeroconf | Via zeroconf | ✅ |

**Verdict**: COMPLIANT. Zeroconf handles the DNS record structure.

### 8. Address Source Priority

| Item | Spec | py-libp2p | go-libp2p | Status |
|------|------|-----------|-----------|--------|
| Primary source | TXT records | Both TXT and A/AAAA | TXT only | ⚠️ |

**Spec**: "The TXT record contains the multiaddresses that the peer is listening on."

**go-libp2p** (`startResolver`):
```go
// We only care about the TXT records.
// Ignore A, AAAA and PTR.
for _, s := range entry.Text {
    if !strings.HasPrefix(s, dnsaddrPrefix) {
        continue
    }
    addr, err := ma.NewMultiaddr(s[len(dnsaddrPrefix):])
    // ...
}
```

**py-libp2p** (`listener.py:146-156`):
```python
# Parse addresses from A/AAAA records
for addr in info.addresses:
    if len(addr) == 4:
        ip = socket.inet_ntoa(addr)
        addrs.append(Multiaddr(f"/ip4/{ip}/tcp/{info.port}"))
    elif len(addr) == 16:
        ip = socket.inet_ntop(socket.AF_INET6, addr)
        addrs.append(Multiaddr(f"/ip6/{ip}/tcp/{info.port}"))
```

**Analysis**: The spec clearly states TXT records are the source of multiaddrs.
go-libp2p ignores A/AAAA and only uses TXT. Our implementation uses A/AAAA as
the primary source and TXT only for peer ID extraction. This is **backwards**.

**Verdict**: NON-COMPLIANT. Should extract addresses from TXT dnsaddr records,
not from A/AAAA records.

### 9. Address Filtering (Unsuitable Protocols)

| Item | Spec | py-libp2p | go-libp2p | Status |
|------|------|-----------|-----------|--------|
| Filter loopback | "should not send" | Yes (`127.0.0.1`, `::1`) | Yes | ✅ |
| Filter circuit relay | Not for LAN | No | `isSuitableForMDNS` | ⚠️ |
| Filter browser transports | Not for LAN | No | `isSuitableForMDNS` | ⚠️ |
| Filter non-.local DNS | Requires unicast DNS | No | `isSuitableForMDNS` | ⚠️ |

**go-libp2p `isSuitableForMDNS`**:
```go
func isSuitableForMDNS(addr ma.Multiaddr) bool {
    // Suitable: /ip4, /ip6, /dns*.local
    // Not suitable: circuit relay, WebTransport, WebRTC, WebSocket, non-.local DNS
}
```

**Analysis**: go-libp2p filters out addresses that aren't suitable for LAN discovery:
- Circuit relay (requires intermediary)
- Browser transports (browsers don't use mDNS)
- Non-.local DNS names (require unicast DNS)

**Verdict**: PARTIALLY COMPLIANT. Loopback is filtered, but missing circuit relay,
browser transport, and non-.local DNS filtering.

### 10. Peer ID Validation

| Item | Spec | py-libp2p | go-libp2p | Status |
|------|------|-----------|-----------|--------|
| Validation | Must be valid peer ID | `Qm` prefix + length check | `peer.AddrInfosFromP2pAddrs` | ⚠️ |

**py-libp2p** (`listener.py:206-229`):
```python
def _validate_peer_id(self, peer_id: str) -> bool:
    if not peer_id.startswith("Qm"):
        return False
    if len(peer_id) < 46 or len(peer_id) > 100:
        return False
    try:
        ID.from_string(peer_id)
        return True
    except Exception:
        return False
```

**Analysis**:
- Only validates `Qm` prefix (SHA2-256 multihash). Newer key types (Ed25519,
  P-256, etc.) have different prefixes and would be rejected.
- go-libp2p uses `peer.AddrInfosFromP2pAddrs` which handles all key types.

**Verdict**: PARTIALLY COMPLIANT. Works for `Qm` peer IDs but rejects newer key types.

### 11. TTL and Cleanup

| Item | Spec | py-libp2p | go-libp2p | Status |
|------|------|-----------|-----------|--------|
| TTL | Not specified | 120s (configurable) | Via zeroconf | ✅ |
| Cleanup | Not specified | Periodic cleanup loop | Context cancellation | ✅ |

**Verdict**: COMPLIANT (no spec requirement).

### 12. Retry Logic

| Item | Spec | py-libp2p | go-libp2p | Status |
|------|------|-----------|-----------|--------|
| Retry | Not specified | Exponential backoff (3 attempts) | Via zeroconf | ✅ |

**Verdict**: COMPLIANT (no spec requirement).

## Critical Issues

### CRITICAL: Address Source Priority is Wrong

**Issue**: Our listener extracts addresses from A/AAAA records instead of TXT records.

**Spec**: "The TXT record contains the multiaddresses that the peer is listening on."

**go-libp2p**:
```go
// We only care about the TXT records.
// Ignore A, AAAA and PTR.
```

**Current py-libp2p** (`listener.py:143-170`):
```python
def _extract_peer_info(self, info: ServiceInfo) -> PeerInfo | None:
    # Parse addresses from A/AAAA records  <-- WRONG
    addrs = []
    for addr in info.addresses:
        ...
    # Parse peer ID from TXT records
    peer_id = self._parse_peer_id_from_txt(info.properties)
    return PeerInfo(peer_id=pid, addrs=addrs)
```

**Fix**: Parse addresses from TXT `dnsaddr` records instead:
```python
def _extract_peer_info(self, info: ServiceInfo) -> PeerInfo | None:
    # Parse peer ID AND addresses from TXT dnsaddr records
    peer_id, addrs = self._parse_from_txt_records(info)
    if not peer_id or not addrs:
        return None
    return PeerInfo(peer_id=pid, addrs=addrs)
```

### HIGH: Missing Address Filtering

**Issue**: go-libp2p filters unsuitable addresses (circuit relay, browser transports,
non-.local DNS). Our implementation doesn't.

**Impact**: When users pass listen addresses containing circuit relay or browser
transports, these would be advertised via mDNS, which is incorrect.

**Fix**: Add `is_suitable_for_mdns()` filter in broadcaster.

### MEDIUM: Peer ID Validation Too Restrictive

**Issue**: Only validates `Qm` prefix. Newer key types (Ed25519 `12D3KooW...`,
P-256 `4qB...`) are rejected.

**Fix**: Remove prefix check, rely on `ID.from_string()` for validation.

## Minor Issues

### 1. Listener `add_service` Returns Early for Own Service

**Current**: `if name == self.service_name: return`

This is correct for filtering, but the spec says "a peer must respond to its own
query." This means we should still register our own service (which we do via
`broadcaster.register()`), just not add it to discovered_services. This is fine.

### 2. TXT Record Key Naming

**Current**: `dnsaddr`, `dnsaddr2`, `dnsaddr3`, ...

**go-libp2p**: Uses separate TXT records, not numbered keys.

**zeroconf behavior**: Multiple TXT records with the same key would overwrite.
Using numbered keys (`dnsaddr2`) is a valid approach to support multiple
addresses in a single properties dict.

**Verdict**: Acceptable alternative.

## Summary

| Category | Status |
|----------|--------|
| Service Name Format | ✅ COMPLIANT |
| Peer Name Generation | ✅ COMPLIANT |
| TXT Record Format | ✅ COMPLIANT |
| Meta Query | ✅ COMPLIANT |
| Private Networks | ✅ COMPLIANT |
| Self-Discovery Filtering | ✅ COMPLIANT |
| Response Structure | ✅ COMPLIANT |
| **Address Source Priority** | **❌ NON-COMPLIANT** |
| **Address Filtering** | **⚠️ PARTIAL** |
| **Peer ID Validation** | **⚠️ PARTIAL** |
| TTL/Cleanup | ✅ COMPLIANT |
| Retry Logic | ✅ COMPLIANT |

**Overall**: 9/12 fully compliant, 2/12 partially compliant, 1/12 non-compliant.

## Recommended Fixes

1. **CRITICAL**: Rewrite `_extract_peer_info` to parse addresses from TXT
   `dnsaddr` records instead of A/AAAA records.

2. **HIGH**: Add `is_suitable_for_mdns()` address filter in broadcaster
   to exclude circuit relay, browser transports, and non-.local DNS.

3. **MEDIUM**: Simplify `_validate_peer_id` to just call `ID.from_string()`
   without prefix check.
