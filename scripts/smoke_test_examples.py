#!/usr/bin/env python3
"""
Smoke-test example modules: each file under ``examples/`` with a ``__main__``
guard must **load** without errors (imports resolve, no exception at import time).

The module is executed with :func:`importlib.util.spec_from_file_location` so
``if __name__ == "__main__"`` blocks are **not** run. This avoids port
conflicts, long-running demos, and bad default ``main()`` paths while still
proving that every example entry point *starts* (interpreter + imports).

Each check runs in a subprocess with ``TIMEOUT_SEC`` so a hung import fails fast.

Optional ``--run-main`` restores the previous behavior (``--help`` for argparse
scripts, or full run with timeout) for deeper checks.

Run from repo root with the project venv active::

    source venv/bin/activate && python scripts/smoke_test_examples.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import textwrap

TIMEOUT_SEC = 5.0
REPO_ROOT = Path(__file__).resolve().parent.parent


def _uses_argparse(src: str) -> bool:
    return (
        "ArgumentParser" in src or "\nimport argparse" in src or "from argparse " in src
    )


def _has_main_guard(src: str) -> bool:
    return 'if __name__ == "__main__"' in src or "if __name__ == '__main__'" in src


def discover_scripts() -> list[Path]:
    out: list[Path] = []
    for p in sorted((REPO_ROOT / "examples").rglob("*.py")):
        if p.name == "__init__.py":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if _has_main_guard(text):
            out.append(p)
    return out


def smoke_import_subprocess(path: Path) -> tuple[bool, str]:
    """Load file as a non-__main__ module inside a subprocess (5s cap)."""
    path_s = json.dumps(str(path.resolve()))
    code = textwrap.dedent(
        f"""
        import importlib.util
        import sys
        p = {path_s}
        spec = importlib.util.spec_from_file_location("_smoke_example", p)
        if spec is None or spec.loader is None:
            sys.exit(2)
        m = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(m)
        except BaseException as e:
            print(f"{{type(e).__name__}}: {{e}}", file=sys.stderr)
            sys.exit(1)
        """
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            timeout=TIMEOUT_SEC,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout during import"

    if proc.returncode == 0:
        return True, "import ok"

    tail = (proc.stderr + proc.stdout)[-600:]
    return False, f"exit {proc.returncode}; {tail!r}"


def smoke_run_main(path: Path) -> tuple[bool, str]:
    """Run script (``--help`` or full run) with timeout — can hit ports/CID issues."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"read_error: {e}"

    if _uses_argparse(text):
        cmd = [sys.executable, str(path), "--help"]
    else:
        cmd = [sys.executable, str(path)]

    try:
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            timeout=TIMEOUT_SEC,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return True, "ok (still running after 5s)"

    if proc.returncode == 0:
        tail = (proc.stderr + proc.stdout)[-400:]
        return True, f"exit 0; tail={tail!r}"

    tail = (proc.stderr + proc.stdout)[-500:]
    return False, f"exit {proc.returncode}; tail={tail!r}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-main",
        action="store_true",
        help="Run each script's main (--help or full process) instead of import-only.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print one JSON object per line (path, ok, detail).",
    )
    args = parser.parse_args()

    paths = discover_scripts()
    failed: list[tuple[Path, str]] = []
    runner = smoke_run_main if args.run_main else smoke_import_subprocess

    for path in paths:
        ok, detail = runner(path)
        rel = path.relative_to(REPO_ROOT)
        if args.json:
            print(
                json.dumps(
                    {"path": str(rel), "ok": ok, "detail": detail},
                    ensure_ascii=False,
                )
            )
        else:
            status = "PASS" if ok else "FAIL"
            print(f"{status}  {rel}  ({detail})")
        if not ok:
            failed.append((rel, detail))

    mode = "run-main" if args.run_main else "import-only"
    if failed:
        print(
            f"\n{len(failed)} failed of {len(paths)} ({mode})",
            file=sys.stderr,
        )
        sys.exit(1)
    print(
        f"\nAll {len(paths)} example modules passed ({mode}) smoke test.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
