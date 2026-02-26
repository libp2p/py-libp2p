# Maintainer Runbook: OSO Health Reporting

This runbook explains local and CI operation for the productized OSO module.

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
