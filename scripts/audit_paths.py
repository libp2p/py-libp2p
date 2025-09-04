#!/usr/bin/env python3
"""
Audit script to identify path handling issues in the py-libp2p codebase.

This script scans for patterns that should be migrated to use the new
cross-platform path utilities.
"""

import argparse
from pathlib import Path
import re
from typing import Any


def scan_for_path_issues(directory: Path) -> dict[str, list[dict[str, Any]]]:
    """
    Scan for path handling issues in the codebase.

    Args:
        directory: Root directory to scan

    Returns:
        Dictionary mapping issue types to lists of found issues

    """
    issues = {
        "hard_coded_slash": [],
        "os_path_join": [],
        "temp_hardcode": [],
        "os_path_dirname": [],
        "os_path_abspath": [],
        "direct_path_concat": [],
    }

    # Patterns to search for
    patterns = {
        "hard_coded_slash": r'["\'][^"\']*\/[^"\']*["\']',
        "os_path_join": r"os\.path\.join\(",
        "temp_hardcode": r'["\']\/tmp\/|["\']C:\\\\',
        "os_path_dirname": r"os\.path\.dirname\(",
        "os_path_abspath": r"os\.path\.abspath\(",
        "direct_path_concat": r'["\'][^"\']*["\']\s*\+\s*["\'][^"\']*["\']',
    }

    # Files to exclude
    exclude_patterns = [
        r"__pycache__",
        r"\.git",
        r"\.pytest_cache",
        r"\.mypy_cache",
        r"\.ruff_cache",
        r"env/",
        r"venv/",
        r"\.venv/",
    ]

    for py_file in directory.rglob("*.py"):
        # Skip excluded files
        if any(re.search(pattern, str(py_file)) for pattern in exclude_patterns):
            continue

        try:
            content = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"Warning: Could not read {py_file} (encoding issue)")
            continue

        for issue_type, pattern in patterns.items():
            matches = re.finditer(pattern, content, re.MULTILINE)
            for match in matches:
                line_num = content[: match.start()].count("\n") + 1
                line_content = content.split("\n")[line_num - 1].strip()

                issues[issue_type].append(
                    {
                        "file": py_file,
                        "line": line_num,
                        "content": match.group(),
                        "full_line": line_content,
                        "relative_path": py_file.relative_to(directory),
                    }
                )

    return issues


def generate_migration_suggestions(issues: dict[str, list[dict[str, Any]]]) -> str:
    """
    Generate migration suggestions for found issues.

    Args:
        issues: Dictionary of found issues

    Returns:
        Formatted string with migration suggestions

    """
    suggestions = []

    for issue_type, issue_list in issues.items():
        if not issue_list:
            continue

        suggestions.append(f"\n## {issue_type.replace('_', ' ').title()}")
        suggestions.append(f"Found {len(issue_list)} instances:")

        for issue in issue_list[:10]:  # Show first 10 examples
            suggestions.append(f"\n### {issue['relative_path']}:{issue['line']}")
            suggestions.append("```python")
            suggestions.append("# Current code:")
            suggestions.append(f"{issue['full_line']}")
            suggestions.append("```")

            # Add migration suggestion based on issue type
            if issue_type == "os_path_join":
                suggestions.append("```python")
                suggestions.append("# Suggested fix:")
                suggestions.append("from libp2p.utils.paths import join_paths")
                suggestions.append(
                    "# Replace os.path.join(a, b, c) with join_paths(a, b, c)"
                )
                suggestions.append("```")
            elif issue_type == "temp_hardcode":
                suggestions.append("```python")
                suggestions.append("# Suggested fix:")
                suggestions.append(
                    "from libp2p.utils.paths import get_temp_dir, create_temp_file"
                )
                temp_fix_msg = (
                    "# Replace hard-coded temp paths with get_temp_dir() or "
                    "create_temp_file()"
                )
                suggestions.append(temp_fix_msg)
                suggestions.append("```")
            elif issue_type == "os_path_dirname":
                suggestions.append("```python")
                suggestions.append("# Suggested fix:")
                suggestions.append("from libp2p.utils.paths import get_script_dir")
                script_dir_fix_msg = (
                    "# Replace os.path.dirname(os.path.abspath(__file__)) with "
                    "get_script_dir(__file__)"
                )
                suggestions.append(script_dir_fix_msg)
                suggestions.append("```")

        if len(issue_list) > 10:
            suggestions.append(f"\n... and {len(issue_list) - 10} more instances")

    return "\n".join(suggestions)


def generate_summary_report(issues: dict[str, list[dict[str, Any]]]) -> str:
    """
    Generate a summary report of all found issues.

    Args:
        issues: Dictionary of found issues

    Returns:
        Formatted summary report

    """
    total_issues = sum(len(issue_list) for issue_list in issues.values())

    report = [
        "# Cross-Platform Path Handling Audit Report",
        "",
        "## Summary",
        f"Total issues found: {total_issues}",
        "",
        "## Issue Breakdown:",
    ]

    for issue_type, issue_list in issues.items():
        if issue_list:
            issue_title = issue_type.replace("_", " ").title()
            instances_count = len(issue_list)
            report.append(f"- **{issue_title}**: {instances_count} instances")

    report.append("")
    report.append("## Priority Matrix:")
    report.append("")
    report.append("| Priority | Issue Type | Risk Level | Impact |")
    report.append("|----------|------------|------------|---------|")

    priority_map = {
        "temp_hardcode": (
            "🔴 P0",
            "HIGH",
            "Core functionality fails on different platforms",
        ),
        "os_path_join": ("🟡 P1", "MEDIUM", "Examples and utilities may break"),
        "os_path_dirname": ("🟡 P1", "MEDIUM", "Script location detection issues"),
        "hard_coded_slash": ("🟢 P2", "LOW", "Future-proofing and consistency"),
        "os_path_abspath": ("🟢 P2", "LOW", "Path resolution consistency"),
        "direct_path_concat": ("🟢 P2", "LOW", "String concatenation issues"),
    }

    for issue_type, issue_list in issues.items():
        if issue_list:
            priority, risk, impact = priority_map.get(
                issue_type, ("🟢 P2", "LOW", "General improvement")
            )
            issue_title = issue_type.replace("_", " ").title()
            report.append(f"| {priority} | {issue_title} | {risk} | {impact} |")

    return "\n".join(report)


def main():
    """Main function to run the audit."""
    parser = argparse.ArgumentParser(
        description="Audit py-libp2p codebase for path handling issues"
    )
    parser.add_argument(
        "--directory",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument("--output", help="Output file for detailed report")
    parser.add_argument(
        "--summary-only", action="store_true", help="Only show summary report"
    )

    args = parser.parse_args()

    directory = Path(args.directory)
    if not directory.exists():
        print(f"Error: Directory {directory} does not exist")
        return 1

    print("🔍 Scanning for path handling issues...")
    issues = scan_for_path_issues(directory)

    # Generate and display summary
    summary = generate_summary_report(issues)
    print(summary)

    if not args.summary_only:
        # Generate detailed suggestions
        suggestions = generate_migration_suggestions(issues)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(summary)
                f.write(suggestions)
            print(f"\n📄 Detailed report saved to {args.output}")
        else:
            print(suggestions)

    return 0


if __name__ == "__main__":
    exit(main())
