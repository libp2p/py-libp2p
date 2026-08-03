# mDNS Spec Compliance Analysis - Round 3

Deep comparison of py-libp2p vs spec vs go-libp2p after Round 2 fixes.

## Spec Requirements (Verbatim)

### Definitions

> - `service-name` is the DNS Service Discovery (DNS-SD) service name for all peers.
>   It is defined as `_p2p._udp.local`.
> - `host-name` is the fully qualified name of the peer. It is derived from the
>   peer's name and `p2p.local`.
> - `peer-name` is the case-insensitive unique identifier of the peer, and is
>   less than 64 characters. Peers SHOULD generate a random, lower-case
>   alphanumeric string of least 32 characters in length when booting up their
>   node. Peers SHOULD NOT use their Peer ID here.

### Response (Find All Peers)

> On receipt of a `find all peers` query, a peer sends a DNS response message
> that contains the answer:
>
> ```
> <service-name> PTR <peer-name>.<service-name>
> ```
>
> The **additional records** of the response contain the peer's discovery details:
>
> ```
> <peer-name>.<service-name> TXT "dnsaddr=..."
> ```
>
> The TXT record contains the multiaddresses that the peer is listening on.
> Each multiaddress is a TXT attribute with the form `dnsaddr=/.../p2p/QmId`.
> Multiple `dnsaddr` attributes and/or TXT records are allowed.

### Find All Response (Additional Records)

> ```
> <peer-name>.<service-name> SRV ... <host-name>
> <host-name>              A <ipv4 address>
> <host-name>              AAAA <ipv6 address>
> ```

### Gotchas

> Many existing tools ignore the Additional Records, and always send individual
> queries for the peer's discovery details. To accommodate this, a peer should
> respond to:
>
> - `<peer-name>.<service-name> SRV`
> - `<peer-name>.<service-name> TXT`
> - `<host-name> A`
> - `<host-name> AAAA`

### Issues Section

> \[ \] mDNS requires link-local addresses. Loopback and "NAT busting" addresses
> should not be sent and must be ignored on receipt?

## Comparison Table

### Definitions

| Item         | Spec                                     | go-libp2p                              | py-libp2p              | Match |
| ------------ | ---------------------------------------- | -------------------------------------- | ---------------------- | ----- |
| service-name | `_p2p._udp.local`                        | `_p2p._udp` (+ `.local` from zeroconf) | `_p2p._udp.local.`     | ✅    |
| peer-name    | random, lowercase, 32-63 chars           | `randomString(32 + rand.Intn(32))`     | `stringGen(63)`        | ✅    |
| host-name    | "derived from peer's name and p2p.local" | `s.peerName` (same as peer-name)       | `socket.gethostname()` | ❌    |

### Response Structure

| Record | Spec                               | go-libp2p           | py-libp2p              | Match |
| ------ | ---------------------------------- | ------------------- | ---------------------- | ----- |
| PTR    | `<service> PTR <peer>.<service>`   | Via zeroconf        | Via zeroconf           | ✅    |
| TXT    | `<peer>.<service> TXT dnsaddr=...` | Via `RegisterProxy` | Via `register_service` | ✅    |
| SRV    | `<peer>.<service> SRV ... <host>`  | Via zeroconf        | Via zeroconf           | ⚠️    |
| A      | `<host> A <ipv4>`                  | Via zeroconf        | Via zeroconf           | ⚠️    |
| AAAA   | `<host> AAAA <ipv6>`               | Via zeroconf        | Via zeroconf           | ⚠️    |

### Address Handling

| Item       | Spec                                        | go-libp2p                                   | py-libp2p                       | Match |
| ---------- | ------------------------------------------- | ------------------------------------------- | ------------------------------- | ----- |
| Source     | Not specified                               | `host.Network().InterfaceListenAddresses()` | Socket probing                  | ⚠️    |
| Filtering  | "link-local", "loopback should not be sent" | `isSuitableForMDNS`                         | `is_suitable_for_mdns`          | ✅    |
| TXT format | `dnsaddr=/.../p2p/QmId`                     | `dnsaddr=` + multiaddr.String()             | `/ip4/{ip}/tcp/{port}/p2p/{id}` | ✅    |
| Multiple   | "Multiple allowed"                          | `[]string` TXTs                             | `dnsaddr`, `dnsaddr2` keys      | ✅    |

### Discovery

| Item           | Spec                                 | go-libp2p                 | py-libp2p                          | Match |
| -------------- | ------------------------------------ | ------------------------- | ---------------------------------- | ----- |
| Query          | `_p2p._udp.local PTR`                | Via zeroconf              | Via zeroconf                       | ✅    |
| Meta query     | `_services._dns-sd._udp.local PTR`   | Via zeroconf              | `META_QUERY_TYPE` + ServiceBrowser | ✅    |
| Self-filter    | "peer must respond to own query"     | `info.ID == s.host.ID()`  | `name == self.service_name`        | ✅    |
| Address source | "TXT record contains multiaddresses" | TXT only (ignores A/AAAA) | TXT primary, A/AAAA fallback       | ✅    |

## Issues Found

### Issue 1: host-name Derivation (MEDIUM)

**Spec**: "host-name is the fully qualified name of the peer. It is derived from the peer's name and p2p.local."

**go-libp2p**: Uses `s.peerName` as the host name in `zeroconf.RegisterProxy`. This means:

- SRV record: `<peer-name>.<service> SRV ... <peer-name>`
- A record: `<peer-name> A <ipv4>`
- AAAA record: `<peer-name> AAAA <ipv6>`

**py-libp2p**: Uses `f"{socket.gethostname()}.local."` as the `server` field. This means:

- SRV record: `<peer-name>.<service> SRV ... <system-hostname>.local`
- A record: `<system-hostname>.local A <ipv4>` (via zeroconf)
- AAAA record: `<system-hostname>.local AAAA <ipv6>` (via zeroconf)

**Impact**: The SRV record references `<system-hostname>.local` but the A/AAAA records may not match if the system hostname doesn't resolve via mDNS. However, since libp2p peers use TXT records (not SRV/A/AAAA), this doesn't affect peer discovery.

**Fix**: Set `server` to `f"{self.peer_name}.{mdns_domain}"` instead of `f"{hostname}.local."`.

### Issue 2: Address Source (LOW)

**Spec**: Not specified how to obtain listen addresses.

**go-libp2p**: Uses `s.host.Network().InterfaceListenAddresses()` which returns actual network interface addresses from the libp2p network service.

**py-libp2p**: Uses socket probing (`connect("8.8.8.8", 80)`) to detect local IPs. This is a heuristic that may miss some interfaces or return unexpected results in complex network configurations.

**Better approach**: Use `host.get_addrs()` which returns the actual listen addresses of the host, already filtered and with `/p2p/{peer_id}` suffix. This is what go-libp2p effectively does (via `InterfaceListenAddresses` + `AddrInfoToP2pAddrs`).

**Impact**: Minor. Both approaches produce similar results on simple networks. Socket probing may fail on containers, VMs, or multi-homed hosts.

**Fix**: Accept `host` parameter in `PeerBroadcaster` and use `host.get_addrs()` for addresses.

### Issue 3: Peer Name Length Randomization (LOW)

**Spec**: "Peers SHOULD generate a random, lower-case alphanumeric string of least 32 characters in length."

**go-libp2p**: `randomString(32 + rand.Intn(32))` = 32-63 chars (random length)

**py-libp2p**: `stringGen(63)` = 63 chars (fixed)

**Impact**: None. Both comply with spec (>=32, \<64). Fixed63 is within range. Randomization of length is a style difference, not a compliance issue.

### Issue 4: ServiceInfo server Field with Listen Addrs (INFO)

When `listen_addrs` are provided to the broadcaster, the `server` field is still set to `f"{hostname}.local."` where hostname is `socket.gethostname()`. This doesn't change based on the listen addresses.

**go-libp2p**: Always uses `s.peerName` as the host name, regardless of addresses.

**Impact**: None for peer discovery (TXT records are used). Only affects DNS-SD browsing tools that use SRV/A/AAAA records.

## Spec Compliance Summary

| Category              | Status       | Notes                                               |
| --------------------- | ------------ | --------------------------------------------------- |
| service-name format   | ✅ COMPLIANT | `_p2p._udp.local`                                   |
| peer-name generation  | ✅ COMPLIANT | random, lowercase, 63 chars                         |
| host-name derivation  | ⚠️ DEVIATES  | Uses system hostname instead of peer-derived        |
| TXT record format     | ✅ COMPLIANT | `dnsaddr=/ip4/.../p2p/QmId`                         |
| Multiple TXT records  | ✅ COMPLIANT | `dnsaddr`, `dnsaddr2`, etc.                         |
| PTR record            | ✅ COMPLIANT | Via zeroconf                                        |
| SRV record            | ⚠️ DEVIATES  | server field is system hostname, not peer-derived   |
| A/AAAA records        | ✅ COMPLIANT | Via zeroconf                                        |
| Address filtering     | ✅ COMPLIANT | Filters loopback, circuit relay, browser transports |
| TXT as address source | ✅ COMPLIANT | Primary source, A/AAAA fallback                     |
| Meta query            | ✅ COMPLIANT | `_services._dns-sd._udp.local`                      |
| Private networks      | � COMPLIANT  | `_p2p-X._udp.local`                                 |
| Self-filtering        | ✅ COMPLIANT | Filters own service name                            |
| Loopback filtering    | ✅ COMPLIANT | `127.0.0.1` excluded                                |

## Verdict

**12/14 fully compliant, 2/14 deviate (host-name derivation, SRV record)**

The two deviations are **non-blocking for peer discovery** because:

1. libp2p peers use TXT records, not SRV/A/AAAA
1. go-libp2p explicitly ignores A/AAAA records in the resolver

However, they affect **interoperability with DNS-SD browsing tools** (e.g., `avahi-browse`, `dns-sd`) that rely on SRV/A/AAAA records.

## Recommended Fixes

1. **Fix host-name**: Set `server=f"{peer_name}.{mdns_domain}"` in ServiceInfo
1. **Fix address source**: Accept `host` param, use `host.get_addrs()` for addresses
1. Both are **low priority** since they don't affect libp2p peer discovery
