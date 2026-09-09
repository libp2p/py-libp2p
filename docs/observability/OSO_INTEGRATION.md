# OSO Integration Guide

This guide explains how to run `py-libp2p` OSO health reporting and use optional
OSO enrichment.

## Prerequisites

1. OSO account: https://www.opensource.observer/
1. Optional API key from account settings
1. Local environment with `py-libp2p` installed

## Configure API Key

Set an environment variable when OSO API enrichment is desired:

```bash
export OSO_API_KEY='your-api-key-here'
```

## Run Health Report

Preferred CLI:

```bash
oso-health-report --repo-root . --repo-slug libp2p/py-libp2p
```

Wrapper CLI:

```bash
python scripts/oso/collect_health_metrics.py --repo-root . --repo-slug libp2p/py-libp2p
```

Outputs:

- `reports/health_metrics.json`
- `reports/health_report.md`

## Notes

- The report continues with partial data if a provider fails.
- OSO integration extends runtime monitoring from `libp2p/rcmgr`; it does not replace it.
- Dependency graph file generation remains documented in `docs/dependency_graph/`.
