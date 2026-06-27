# py-ipfs-lite Documentation Review — Round 2

> Checked against commit `7bd448d`. Verified all 8 previously-flagged items directly against
> the files (not just commit messages), re-ran the full link-integrity check across all 23
> markdown files, and cross-checked the two brand-new content files (`comparison.md`,
> `CHANGELOG.md`) against the actual current code, the same way I checked the reference docs
> last time.

______________________________________________________________________

## Verdict: All 8 previous items genuinely fixed. Two new factual errors found in `comparison.md` — both ironically *undersell* what the code actually does.

______________________________________________________________________

## Previous 8 Items — All Confirmed Fixed

| #   | Item                                       | Verified                                                             |
| --- | ------------------------------------------ | -------------------------------------------------------------------- |
| 1   | Broken link in `examples-index.md` row 02  | ✅ Now `../guides/dht-and-routing.md`, matches row 10's correct path |
| 2   | 13 stale "(coming soon)" tags              | ✅ Zero remaining (`grep -c "coming soon"` → 0)                      |
| 3   | README examples-index link as plain text   | ✅ Now a real markdown link                                          |
| 4   | README missing link to `docs/index.md`     | ✅ "Browse all documentation" row added                              |
| 5   | `python-sdk.md` missing 4 accessor methods | ✅ Added as a "Subsystem Accessors" table — see note below           |
| 6   | `py-ipfs-lite-analysis.md` leftover        | ✅ Removed                                                           |
| 7   | `docs/comparison.md` missing               | ✅ Added — see findings below                                        |
| 8   | Root meta files missing                    | ✅ `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md` all added        |

Full link-integrity re-check across all 23 markdown files (docs/ + the 4 root files): **0 broken links.**

### Small accuracy note on item 5

I checked the new accessor table against `peer.py`. Three of four are exactly right (`session()` → `self`, `block_store()` → `self.blockstore`, `block_service()` → `self.dag_service`, which is a real `MerkleDag`). `exchange()` is listed as returning type `Bitswap`, but the actual runtime object is an internally-defined `ExchangeAdapter` wrapper, not a class literally named `Bitswap`. The prose description ("Returns the Bitswap exchange instance") is fine — it's only the type-column label that's slightly off. Trivial, not worth a separate commit on its own, just worth knowing.

______________________________________________________________________

## New Findings

### 1. `comparison.md`: IPNI row is stale — describes the *pre-fix* behavior 🟡

The feature matrix says:

```
| **IPNI (`cid.contact`)** | ✅ (Resolve only) | ❌ | ✅ |
```

and the "out of scope" section states outright: *"While we resolve CIDs from IPNI, we do not publish to it... Content added via py-ipfs-lite is announced to the KadDHT instead."*

This was true two review rounds ago — and was specifically fixed since then. I re-checked `routing.py` directly: `DelegatedHTTPRouting.provide()` does a real `PUT /routing/v1/providers/{key}` per IPIP-337, with the host's PeerID and addresses. IPNI announce works today. This section needs to flip from "out of scope" to a feature-matrix ✅, and the explanatory paragraph should go (or be replaced with something like "IPNI announce uses unauthenticated peer-schema records — see the Production Deployment Guide's security notes for what that means in practice," since the *trust* angle is still worth keeping, just not framed as "doesn't exist").

This is the one item across both documentation rounds that's a genuine factual regression rather than a freshness/connective-tissue issue — and it happens to undersell a real capability, which is a strange thing to have happen by accident in marketing-adjacent material.

### 2. `comparison.md`: QUIC row misattributes the gap to the wrong layer 🟡

```
| **Transport** | TCP, Noise | TCP, Noise, QUIC | All | QUIC is not yet supported in `py-libp2p` |
```

I checked this directly: the installed `libp2p` package (canonical `libp2p/py-libp2p`, the same one `py-ipfs-lite` depends on) **does** ship a QUIC transport module (`libp2p.transport.quic`). The gap is entirely in `py-ipfs-lite`'s own `_create_host()` — it only passes Noise into `sec_opt` when calling `new_host()` and never wires in a QUIC transport option. That's a `py-ipfs-lite` TODO, not an upstream blocker.

Worth fixing the wording for two reasons: it's more accurate, and it's actually a *better* story for you — "available upstream, we haven't wired it in yet" is a much smaller, more credible gap to mention in a comparison doc than "blocked on the dependency." Something like:

```
| **Transport** | TCP, Noise | TCP, Noise, QUIC | All | QUIC ships in py-libp2p; not yet wired into py-ipfs-lite's host construction |
```

### 3. `CHANGELOG.md`: names the wrong async library for the CAR I/O fix 🟢

> *"Switched CAR export from synchronous blocking file I/O to async I/O via `anyio`..."*

I checked `car.py` directly — it imports and uses `trio` (`trio.open_file`), not `anyio`. One-word fix (`anyio` → `trio`). Low-stakes since it's changelog prose, not a reference page anyone would copy code from, but worth correcting since the whole point of a changelog is to be a reliable record.

______________________________________________________________________

## Where Things Stand

Everything mechanical (links, freshness tags, missing files) from round 1 is genuinely closed out — zero broken links across the entire docs tree now, which is a good bar to hold going forward. The two `comparison.md` items are worth a quick second pass since they're not just stale, they're actively selling the project short on two features that already work. Realistically a 10-minute fix: flip the IPNI row, reword the QUIC row and its footnote, swap `anyio`→`trio` in the changelog.

After that, I'd consider the documentation set complete and accurate against the current codebase — nothing else turned up across either review pass.
