#!/usr/bin/env python3
r"""
Run Python↔Python perf tests locally (no Docker, no Redis).

Spawns listener + dialer subprocesses using interop/perf/perf_test.py with
PERF_LOCAL_ADDR_FILE for address handoff. Matches perf harness env vars where
possible so yamux/mplex tuning can be iterated quickly.

Examples:
  # tcp + noise + yamux (default stack)
  ./scripts/perf/run_local_perf.py

  # Full python self-matrix (8 stacks from perf/images.yaml)
  ./scripts/perf/run_local_perf.py --matrix

  # Shorter run for debugging
  UPLOAD_BYTES=67108864 UPLOAD_ITERATIONS=2 ./scripts/perf/run_local_perf.py --quick

  # Yamux A/B
  PY_YAMUX_DISABLE_HYSTERESIS=1 ./scripts/perf/run_local_perf.py \\
      -t tcp -s noise -m yamux
  PY_YAMUX_ASSUME_RTT_MS=1 PY_YAMUX_BATCH_THRESHOLD_DIV=2 \\
      ./scripts/perf/run_local_perf.py

From repo root (editable install recommended):
  pip install -e .
  python scripts/perf/run_local_perf.py --matrix

"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

# scripts/perf -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
PERF_ENTRY = REPO_ROOT / "interop" / "perf" / "perf_test.py"


def _python_executable() -> str:
    """Prefer repo .venv when present (avoids system Python missing deps)."""
    venv_py = REPO_ROOT / ".venv" / "bin" / "python"
    if venv_py.is_file():
        return str(venv_py)
    return sys.executable


# Same stacks as python-v0.x in unified-testing perf/images.yaml
# (tcp/ws × noise/tls × yamux/mplex)
PYTHON_PERF_STACKS: tuple[tuple[str, str | None, str | None], ...] = (
    ("tcp", "noise", "yamux"),
    ("tcp", "noise", "mplex"),
    ("tcp", "tls", "yamux"),
    ("tcp", "tls", "mplex"),
    ("ws", "noise", "yamux"),
    ("ws", "noise", "mplex"),
    ("ws", "tls", "yamux"),
    ("ws", "tls", "mplex"),
)

# Passed through from the parent environment when set (perf harness / shell exports).
PASSTHROUGH_ENV_KEYS: tuple[str, ...] = (
    "DEBUG",
    "LIBP2P_DEBUG",
    "LIBP2P_DEBUG_FILE",
    "PY_YAMUX_DEBUG",
    "PY_YAMUX_DISABLE_HYSTERESIS",
    "PY_YAMUX_RELEASE_ON_READ",
    "PY_YAMUX_ASSUME_RTT_MS",
    "PY_YAMUX_BATCH_THRESHOLD_DIV",
    "PERF_WRITE_BLOCK_SIZE",
    "UPLOAD_BYTES",
    "DOWNLOAD_BYTES",
    "UPLOAD_ITERATIONS",
    "DOWNLOAD_ITERATIONS",
    "LATENCY_ITERATIONS",
    "TEST_TIMEOUT_SECS",
    "DIAL_TIMEOUT_SECS",
    "UPGRADE_TIMEOUT_SECS",
    "STREAM_NEGOTIATE_TIMEOUT_SECS",
    "NEGOTIATE_TIMEOUT_SECS",
    "QUIC_CONNECTION_TIMEOUT_SECS",
    "QUIC_IDLE_TIMEOUT_SECS",
    "LISTENER_IP",
)

QUICK_DEFAULTS: Mapping[str, str] = {
    "UPLOAD_BYTES": "67108864",
    "DOWNLOAD_BYTES": "67108864",
    "UPLOAD_ITERATIONS": "2",
    "DOWNLOAD_ITERATIONS": "2",
    "LATENCY_ITERATIONS": "10",
}


@dataclass(frozen=True)
class MetricSummary:
    min: float
    median: float
    max: float
    unit: str

    def format_median(self) -> str:
        if self.unit == "ms":
            return f"{self.median:.3f} {self.unit}"
        return f"{self.median:.2f} {self.unit}"


@dataclass
class TestResult:
    stack: Stack
    rc: int
    elapsed_secs: float
    upload: MetricSummary | None = None
    download: MetricSummary | None = None
    latency: MetricSummary | None = None

    @property
    def passed(self) -> bool:
        return self.rc == 0

    @property
    def status(self) -> str:
        if self.rc == 0:
            return "PASS"
        if self.rc == 124:
            return "TIMEOUT"
        return f"FAIL({self.rc})"


@dataclass(frozen=True)
class Stack:
    transport: str
    secure: str | None
    muxer: str | None

    @property
    def label(self) -> str:
        parts = [self.transport]
        if self.secure:
            parts.append(self.secure)
        if self.muxer:
            parts.append(self.muxer)
        return "+".join(parts)


def _parse_stack(transport: str, secure: str | None, muxer: str | None) -> Stack:
    if transport == "quic-v1":
        return Stack(transport, secure or None, muxer or None)
    if not secure or not muxer:
        raise SystemExit(
            f"{transport} requires --secure and --muxer (e.g. -t tcp -s noise -m yamux)"
        )
    return Stack(transport, secure, muxer)


def _build_role_env(
    *,
    stack: Stack,
    is_dialer: bool,
    addr_file: Path,
    test_key: str,
    debug: bool,
    extra: Mapping[str, str],
) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in PASSTHROUGH_ENV_KEYS and v}
    env.update(extra)
    env.update(
        {
            "IS_DIALER": "true" if is_dialer else "false",
            "PERF_LOCAL_ADDR_FILE": str(addr_file),
            "TEST_KEY": test_key,
            "TRANSPORT": stack.transport,
            "LISTENER_IP": env.get("LISTENER_IP", "0.0.0.0"),
            "DEBUG": "true" if debug else env.get("DEBUG", "false"),
        }
    )
    if stack.secure:
        env["SECURE_CHANNEL"] = stack.secure
    if stack.muxer:
        env["MUXER"] = stack.muxer
    if debug:
        env["PY_YAMUX_DEBUG"] = "1"
    if is_dialer:
        env.setdefault("UPLOAD_BYTES", "1073741824")
        env.setdefault("DOWNLOAD_BYTES", "1073741824")
        env.setdefault("UPLOAD_ITERATIONS", "10")
        env.setdefault("DOWNLOAD_ITERATIONS", "10")
        env.setdefault("LATENCY_ITERATIONS", "100")
    env.setdefault("TEST_TIMEOUT_SECS", "300")
    return env


def _parse_perf_stdout(
    stdout: str,
) -> tuple[MetricSummary | None, MetricSummary | None, MetricSummary | None]:
    """Parse upload/download/latency blocks from perf_test dialer stdout."""

    def _section(name: str) -> MetricSummary | None:
        in_section = False
        values: dict[str, str] = {}
        for line in stdout.splitlines():
            if line == f"{name}:":
                in_section = True
                values = {}
                continue
            if in_section:
                if not line.startswith("  "):
                    break
                key, _, raw = line.strip().partition(": ")
                values[key] = raw
        if "median" not in values or "unit" not in values:
            return None
        return MetricSummary(
            min=float(values.get("min", values["median"])),
            median=float(values["median"]),
            max=float(values.get("max", values["median"])),
            unit=values["unit"],
        )

    return _section("upload"), _section("download"), _section("latency")


def _format_duration(secs: float) -> str:
    if secs < 60:
        return f"{secs:.1f}s"
    minutes, remainder = divmod(int(secs), 60)
    if remainder:
        return f"{minutes}m{remainder}s"
    return f"{minutes}m"


def _active_yamux_env() -> list[str]:
    keys = (
        "PY_YAMUX_DISABLE_HYSTERESIS",
        "PY_YAMUX_RELEASE_ON_READ",
        "PY_YAMUX_ASSUME_RTT_MS",
        "PY_YAMUX_BATCH_THRESHOLD_DIV",
        "PY_YAMUX_DEBUG",
        "PERF_WRITE_BLOCK_SIZE",
    )
    return [f"{k}={os.environ[k]}" for k in keys if os.environ.get(k)]


def _print_summary(results: list[TestResult]) -> None:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    total_elapsed = sum(r.elapsed_secs for r in results)

    print("", file=sys.stderr)
    print("=" * 88, file=sys.stderr)
    print(
        f" PERF SUMMARY — {passed}/{total} passed, "
        f"total {_format_duration(total_elapsed)}",
        file=sys.stderr,
    )
    yamux_env = _active_yamux_env()
    if yamux_env:
        print(f" tuning: {', '.join(yamux_env)}", file=sys.stderr)
    print("=" * 88, file=sys.stderr)

    label_w = max(len(r.stack.label) for r in results)
    label_w = max(label_w, len("Stack"))
    header = (
        f"{'Stack':<{label_w}}  {'Status':<8}  {'Time':>7}  "
        f"{'Upload':>12}  {'Download':>12}  {'Latency':>12}"
    )
    print(header, file=sys.stderr)
    print("-" * len(header), file=sys.stderr)

    for r in results:
        upload = r.upload.format_median() if r.upload else "—"
        download = r.download.format_median() if r.download else "—"
        latency = r.latency.format_median() if r.latency else "—"
        print(
            f"{r.stack.label:<{label_w}}  {r.status:<8}  "
            f"{_format_duration(r.elapsed_secs):>7}  "
            f"{upload:>12}  {download:>12}  {latency:>12}",
            file=sys.stderr,
        )

    print("=" * 88, file=sys.stderr)

    for r in results:
        if not r.passed:
            continue
        if r.upload and r.download and r.latency:
            print(
                f"  {r.stack.label}: upload {r.upload.min:.2f}–{r.upload.max:.2f} "
                f"{r.upload.unit} (median {r.upload.median:.2f}), "
                f"download {r.download.min:.2f}–{r.download.max:.2f} "
                f"{r.download.unit} (median {r.download.median:.2f}), "
                f"latency {r.latency.min:.3f}–{r.latency.max:.3f} "
                f"{r.latency.unit} (median {r.latency.median:.3f})",
                file=sys.stderr,
            )
    print("", file=sys.stderr)


def _run_subprocess(
    role: str,
    env: dict[str, str],
    *,
    timeout: float | None,
    log_dir: Path | None,
) -> subprocess.Popen[str]:
    if log_dir:
        err_path = log_dir / f"{role}.stderr"
        err_f = err_path.open("w", encoding="utf-8")
    else:
        err_f = None
    cmd = [_python_executable(), str(PERF_ENTRY)]
    print(f"[run_local_perf] starting {role}: {' '.join(cmd)}", file=sys.stderr)
    return subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE if role == "dialer" else None,
        stderr=err_f if err_f else None,
        text=True,
    )


def run_one_stack(
    stack: Stack,
    *,
    timeout_secs: int,
    debug: bool,
    quick: bool,
    log_dir: Path | None,
    extra_env: Mapping[str, str],
) -> TestResult:
    started = time.monotonic()
    if not PERF_ENTRY.is_file():
        print(f"perf entry not found: {PERF_ENTRY}", file=sys.stderr)
        return TestResult(stack=stack, rc=1, elapsed_secs=0.0)

    overrides = dict(extra_env)
    if quick:
        for k, v in QUICK_DEFAULTS.items():
            overrides.setdefault(k, v)

    with tempfile.TemporaryDirectory(prefix="py-libp2p-perf-") as tmp:
        addr_file = Path(tmp) / "listener_multiaddr"
        addr_file.touch()
        test_key = "local"

        listener_env = _build_role_env(
            stack=stack,
            is_dialer=False,
            addr_file=addr_file,
            test_key=test_key,
            debug=debug,
            extra=overrides,
        )
        dialer_env = _build_role_env(
            stack=stack,
            is_dialer=True,
            addr_file=addr_file,
            test_key=test_key,
            debug=debug,
            extra=overrides,
        )

        listener = _run_subprocess(
            "listener", listener_env, timeout=None, log_dir=log_dir
        )
        time.sleep(0.5)
        dialer = _run_subprocess(
            "dialer", dialer_env, timeout=timeout_secs, log_dir=log_dir
        )

        dialer_rc = 1
        dialer_stdout = ""
        try:
            assert dialer.stdout is not None
            dialer_stdout, _ = dialer.communicate(timeout=timeout_secs)
            dialer_rc = dialer.returncode or 0
        except subprocess.TimeoutExpired:
            dialer.kill()
            print(
                f"[run_local_perf] dialer timed out after {timeout_secs}s",
                file=sys.stderr,
            )
            dialer_rc = 124
        finally:
            listener.terminate()
            try:
                listener.wait(timeout=30)
            except subprocess.TimeoutExpired:
                listener.kill()
                listener.wait(timeout=10)

        if dialer_stdout:
            print(dialer_stdout, end="" if dialer_stdout.endswith("\n") else "\n")

        upload, download, latency = _parse_perf_stdout(dialer_stdout)
        elapsed = time.monotonic() - started
        result = TestResult(
            stack=stack,
            rc=dialer_rc,
            elapsed_secs=elapsed,
            upload=upload,
            download=download,
            latency=latency,
        )
        line = f"[run_local_perf] {stack.label}: {result.status}"
        if upload:
            line += f" — upload {upload.format_median()}"
        if download:
            line += f", download {download.format_median()}"
        if latency:
            line += f", latency {latency.format_median()}"
        line += f" ({_format_duration(elapsed)})"
        print(line, file=sys.stderr)
        return result


def _stacks_from_args(args: argparse.Namespace) -> list[Stack]:
    if args.matrix:
        return [Stack(t, s, m) for t, s, m in PYTHON_PERF_STACKS]
    if args.stack_index is not None:
        idx = args.stack_index
        if idx < 0 or idx >= len(PYTHON_PERF_STACKS):
            raise SystemExit(f"--stack-index must be 0..{len(PYTHON_PERF_STACKS) - 1}")
        t, s, m = PYTHON_PERF_STACKS[idx]
        return [_parse_stack(t, s, m)]
    return [
        _parse_stack(
            args.transport,
            args.secure,
            args.muxer,
        )
    ]


def _check_imports() -> None:
    py = _python_executable()
    probe = subprocess.run(
        [py, "-c", "import multiaddr, redis, trio, libp2p"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        print(probe.stderr or probe.stdout, file=sys.stderr)
        raise SystemExit(
            "Missing perf dependencies. From repo root:\n"
            "  uv pip install --python .venv/bin/python -e .\n"
            "  uv pip install --python .venv/bin/python redis cryptography"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-t",
        "--transport",
        default="tcp",
        help="TRANSPORT (default: tcp). Use with -s/-m unless --matrix",
    )
    parser.add_argument(
        "-s",
        "--secure",
        default="noise",
        help="SECURE_CHANNEL (default: noise)",
    )
    parser.add_argument(
        "-m",
        "--muxer",
        default="yamux",
        help="MUXER (default: yamux)",
    )
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="Run all 8 python-v0.x perf stacks (tcp/ws × noise/tls × yamux/mplex)",
    )
    parser.add_argument(
        "--stack-index",
        type=int,
        metavar="N",
        help=f"Run PYTHON_PERF_STACKS[N] (0..{len(PYTHON_PERF_STACKS) - 1})",
    )
    parser.add_argument(
        "--list-stacks",
        action="store_true",
        help="Print matrix indices and exit",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Smaller UPLOAD/DOWNLOAD bytes and fewer iterations (see QUICK_DEFAULTS)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Set DEBUG=true (enables targeted libp2p loggers in perf_test)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="SECS",
        help="Subprocess timeout for dialer (default: TEST_TIMEOUT_SECS or 300)",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Write listener/dialer stderr to this directory",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop --matrix on first failure",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.list_stacks:
        for i, (t, s, m) in enumerate(PYTHON_PERF_STACKS):
            print(f"{i}: {t}+{s}+{m}")
        return 0

    _check_imports()

    if args.matrix and (
        args.transport != "tcp" or args.secure != "noise" or args.muxer != "yamux"
    ):
        print(
            "Note: -t/-s/-m are ignored with --matrix",
            file=sys.stderr,
        )

    stacks = _stacks_from_args(args)
    timeout = args.timeout
    if timeout is None:
        raw = os.getenv("TEST_TIMEOUT_SECS") or os.getenv("PERF_TEST_TIMEOUT_SECS")
        timeout = int(raw) if raw else 300

    failures = 0
    results: list[TestResult] = []
    for stack in stacks:
        print(f"\n=== {stack.label} ===", file=sys.stderr)
        result = run_one_stack(
            stack,
            timeout_secs=timeout,
            debug=args.debug,
            quick=args.quick,
            log_dir=args.log_dir,
            extra_env={},
        )
        results.append(result)
        if not result.passed:
            failures += 1
            if args.fail_fast:
                break

    sys.stdout.flush()
    _print_summary(results)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
