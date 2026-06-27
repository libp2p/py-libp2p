# py-ipfs-lite Documentation Review

> Checked against commit `d96029c`. Same standard as the code reviews: I didn't just read
> the docs, I cross-checked every reference page against the actual source (`config.py`,
> `parser.py`, `api.py`, `peer.py`), ran a link-integrity check across all 19 files, and
> live-tested the daemon against the exact `curl` commands written in the README, tutorial
> 02, and the HTTP API reference.

______________________________________________________________________

## Verdict: Strong. The reference docs are genuinely accurate, not just plausible-looking. A handful of small, fixable issues — mostly leftover from writing pages in a different order than they ended up linking to each other.

18 of the 19 files from the plan got built (only `docs/comparison.md` is still missing), plus you completed all three phases I'd sequenced as later priorities — tutorials, full reference, and the index — in the same push. That's faster than the roadmap assumed.

______________________________________________________________________

## What I Verified Is Actually Correct (not just "looks reasonable")

This is the part worth knowing, because it's the part that matters most — wrong reference docs are worse than no docs.

- **`Config` and `AddParams` dataclasses** in `python-sdk.md` — diffed field-by-field against `config.py`. Exact match, including defaults, including the fields that were *removed* in your last cleanup round (no stale `uncached_blockstore`-style ghosts).
- **CLI reference** (`cli.md`) — every flag, type, and default for all 5 subcommands cross-checked against `parser.py`. Exact match, including the easy-to-miss global `--debug` flag.
- **HTTP API reference** (`http-api.md`) — all 17 `/api/v0/*` routes (25 GET+POST combinations) cross-checked against `api.py`. Exact match. `/debug/metrics/prometheus` is correctly documented outside the `/api/v0/` reference page, in `observability.md` instead, which is the right call.
- **Live-tested**, not just read: ran the daemon and fired the exact `curl` commands from the README, tutorial 02, and `http-api.md` at it —
  - `POST /api/v0/add` → response shape matches exactly (`Name`/`Hash`/`Size`)
  - `POST /api/v0/cat` → returned the right content
  - `POST /api/v0/id` → response shape matches exactly (`ID`/`Addresses`)
  - `POST /api/v0/dag/put` → response shape matches exactly (`{"Cid": {"/": ...}}`)
  - The CLI entrypoint (`py-ipfs-lite --help`) matches the documented subcommand list exactly
- **The IPNS trust-model walkthrough** in `ipns.md` (Example 18) — I re-ran the actual example and diffed its real output against the "full output" block in the doc. It matches, word for word. The explanation of *why* each forgery strategy fails (PeerID/pubKey mismatch vs. signature-key mismatch) is technically correct, not hand-waved — this is genuinely good security writing.

That's a meaningful amount of independently-verified accuracy across reference material that's tedious to get exactly right. Good work.

______________________________________________________________________

## Issues Found

### 1. Broken relative link in `examples-index.md` 🟡

Row 02 links to `./dht-and-routing.md`, which resolves relative to `docs/reference/` (where `examples-index.md` lives) — but the file is actually in `docs/guides/`. Row 10 links to the same target correctly (`../guides/dht-and-routing.md`), so this is a one-off typo, not a misunderstanding of the folder structure.

```diff
- | [DHT and Routing](./dht-and-routing.md) *(coming soon)*
+ | [DHT and Routing](../guides/dht-and-routing.md)
```

### 2. 13 stale "(coming soon)" tags in `examples-index.md` 🟡

`examples-index.md` was written before several of the guides it links to existed yet (confirmed from commit order — it landed before `persistence-and-gc.md`, `dht-and-routing.md`, `streaming-large-files.md`, `http-api-daemon.md`, `observability.md`, and tutorial 01 were written). The tags were accurate at the time but never revisited once those pages shipped. Affected rows: **01, 02, 03, 04, 05a, 05b, 06, 07, 10, 12, 16, 17, 21** — 13 of the 21 rows currently claim a guide is "coming soon" when it's already there. Quick fix: search-and-remove `*(coming soon)*` from this file now that everything in Phase 1–3 is done.

### 3. README's link to the examples index isn't a link 🟡

In the "What's Next" table:

```markdown
| See the full list of all 21 examples with one-line descriptions | `docs/reference/examples-index.md` *(coming soon)* |
```

This is plain text, not a markdown link — and the file has existed since `fc1af55`. Same root cause as #2 (written before the target existed, never updated). Fix:

```markdown
| See the full list of all 21 examples with one-line descriptions | [docs/reference/examples-index.md](docs/reference/examples-index.md) |
```

### 4. README never links to `docs/index.md` itself 🟡

The "What's Next" table links to five individual guides but not to the documentation homepage/sitemap. Someone who wants to browse everything (rather than jump straight to one of your five chosen highlights) has no link to follow. Worth adding a row like:

```markdown
| Browse all documentation | [docs/index.md](docs/index.md) |
```

### 5. `python-sdk.md` is missing 4 real methods 🟡

`session()`, `block_store()`, `exchange()`, and `block_service()` exist on `Peer` (verified directly against `peer.py`) but aren't documented as methods or mentioned under "Attributes." This is worth closing specifically because `exchange()` is the one method that had a real shipped bug in an earlier round — it's exactly the kind of low-traffic, easy-to-overlook accessor that benefits most from being written down. These four are quick additions, similar format to the existing "Attributes" table or as a short "Advanced / Embedding" subsection.

### 6. `docs/comparison.md` was never created ⚪

Not urgent — it was Phase 2 in the original roadmap and everything more pressing got built first, which was the right call. You already have the raw material for it (the feature-parity table from our review rounds); it's mostly a formatting pass away from existing, whenever it's useful for you (e.g. ahead of a talk where "how is this different from Kubo" will come up).

### 7. Root-level meta files still pending ⚪

`CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md` — these were Phase 4 (lowest priority) in the original plan and weren't part of this push. Still fine to leave for later; nothing about the current state is worse for their absence.

### 8. `py-ipfs-lite-analysis.md` is still sitting in the repo root ⚪

Unrelated to this docs push specifically (I've flagged it twice before) — my original analysis doc is still tracked at the repo root from several rounds ago. Harmless, just a `git rm` away from being tidy, and slightly odd to have alongside a proper `docs/` folder now.

______________________________________________________________________

## Priority If You Want to Clean Up Before Anything Else

Items 1–4 are all small, mechanical text fixes in two files (`README.md`, `docs/reference/examples-index.md`) — realistically a 10-minute pass. Item 5 is a slightly longer but still short addition to one file. Items 6–8 are genuinely fine to leave for whenever.

Nothing here is a "the docs are wrong" problem — everything a reader would actually rely on (signatures, flags, endpoint shapes, the security demo's claims) checked out against the real, running system. The issues are all in the connective tissue (links, freshness markers) rather than the content itself, which is the better category of problem to have.
