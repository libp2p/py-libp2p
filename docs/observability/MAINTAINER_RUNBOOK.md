# Maintainer Runbook: OSO Health Reporting

This runbook explains local and CI operation for the productized OSO module, and
includes a repeatable workflow to validate health report data accuracy.

## Local Execution

Preferred command:

```bash
oso-health-report --repo-root . --repo-slug libp2p/py-libp2p
```

Operational wrapper:

```bash
python scripts/oso/collect_health_metrics.py --repo-root . --repo-slug libp2p/py-libp2p
```

Outputs:

- `reports/health_metrics.json`
- `reports/health_report.md`

## CI Workflow

- Workflow file: `.github/workflows/oso-health-report.yml`
- Schedule: weekly Monday 06:00 UTC + manual trigger
- Behavior: report-only, uploads JSON/Markdown artifacts

## Secrets

Set in GitHub repository secrets:

- `OSO_API_KEY` (optional)
- `GITHUB_TOKEN` is automatically provided by GitHub Actions

## Data Sources

Each report includes status for:

- `github`: `ok` or `error`
- `oso`: `ok`, `error`, or `not_configured`
- `rcmgr`: local baseline metrics snapshot

## Accuracy Check Workflow

### Step 1: Run two dry-run profiles

Run from repository root with virtual environment activated.

Profile A: baseline without OSO key (graceful degradation check).

```bash
unset OSO_API_KEY
python scripts/oso/collect_health_metrics.py \
  --repo-root . \
  --repo-slug libp2p/py-libp2p \
  --json-output reports/health_metrics.baseline.json \
  --md-output reports/health_report.baseline.md
```

Profile B: full external profile (live-source consistency check).

```bash
export GITHUB_TOKEN="<github_token>"
export OSO_API_KEY="<oso_api_key>"
python scripts/oso/collect_health_metrics.py \
  --repo-root . \
  --repo-slug libp2p/py-libp2p \
  --json-output reports/health_metrics.full.json \
  --md-output reports/health_report.full.md
```

### Step 2: Compare outputs deterministically

Normalize both JSON outputs and diff them:

```bash
jq -S . reports/health_metrics.baseline.json > /tmp/health_baseline.normalized.json
jq -S . reports/health_metrics.full.json > /tmp/health_full.normalized.json
diff -u /tmp/health_baseline.normalized.json /tmp/health_full.normalized.json
```

Classify differences as:

- Expected drift: `generated_at`, recent activity windows, live-source timing.
- Investigate: source status flips, dependency count mismatches, missing metric sections.

### Step 3: Spot-check source-of-truth fields

Use GitHub API checks for external fields:

```bash
gh api repos/libp2p/py-libp2p > /tmp/repo_meta.json
gh api repos/libp2p/py-libp2p/releases --paginate > /tmp/releases.json
gh api repos/libp2p/py-libp2p/issues -f state=all -f per_page=100 > /tmp/issues.json
gh api repos/libp2p/py-libp2p/commits -f per_page=100 > /tmp/commits.json
```

Compare against report fields:

- Popularity (`stars`, `forks`, `watchers`) vs repo metadata.
- Release cadence inputs (`published_at`) vs releases payload.
- Issue responsiveness inputs (`created_at`, `closed_at`, `updated_at` proxy logic).
- Contributor trend inputs (`committed_at`, `author.login`) vs commits payload.
- Dependency topology and duplicates vs `pyproject.toml`.

Security proxy note: OSV results are package-name based and can over-report if
version context is missing.

### Step 4: Apply acceptance criteria

For full profile (`GITHUB_TOKEN` and `OSO_API_KEY` set):

- `source_status.github` must be `ok`.
- `source_status.oso` must be `ok`.
- Critical metric sections must not be empty.
- Dependency counts must align with parsed `pyproject.toml`.

For baseline profile (`OSO_API_KEY` unset):

- `source_status.oso` should be `not_configured`.
- `source_status.github` may be `ok` or `error`, but `source_status.notes` must
  explain provider failures.

### Step 5: Triage anomalies

If data looks incorrect:

1. Re-run same profile and confirm reproducibility.
1. Check `source_status.notes` for provider/network errors.
1. Determine classification:
   - expected live drift,
   - source outage/rate-limit,
   - parser/logic defect.
1. For persistent defects, open a follow-up issue with:
   - expected value,
   - observed value,
   - output file path and timestamp,
   - relevant API payload snippets.

## Optional Hardening Automation

Use the validation helper script:

```bash
python scripts/oso/validate_health_report_accuracy.py \
  --report reports/health_metrics.full.json \
  --repo-slug libp2p/py-libp2p \
  --github-token "$GITHUB_TOKEN"
```

The script exits non-zero when required checks fail. This can be used as a
non-blocking CI signal first, and promoted to required once stable.
