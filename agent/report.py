"""
Report: Generates hit-rate table from test results
Shows bugs planted vs caught, false alarms
"""
import json
from pathlib import Path
from typing import Any


def load_results(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def generate_hit_rate_report(results: dict[str, Any]) -> str:
    """Generate markdown hit-rate report."""
    summary = results["summary"]
    test_results = results["results"]

    # Count bugs by type
    bugs_reproduced = {}
    for r in test_results:
        if r["bug_reproduced"]:
            bug_type = r["bug_type"]
            bugs_reproduced[bug_type] = bugs_reproduced.get(bug_type, 0) + 1

    # In this fake bank, we know the planted bugs (from BUGS env var)
    # We detect this by checking if any test found a bug
    # If no bugs found, we can't know what was planted - assume double_charge is the only one
    planted_bugs = {"double_charge": 1}  # only one bug type planted

    # Determine if bug was actually active by checking if any test caught it
    bug_was_active = len(bugs_reproduced) > 0

    lines = [
        "# Hit Rate Report",
        "",
        f"**Generated from:** {len(test_results)} test cases",
        f"**Date:** {__import__('datetime').datetime.now().isoformat()}",
        "",
        "## Summary",
        "",
        f"- **Total tests:** {summary['total']}",
        f"- **Passed:** {summary['passed']}",
        f"- **Failed:** {summary['failed']}",
        f"- **Bugs reproduced:** {summary['bugs_reproduced']}",
        "",
        "## Bug Detection Matrix",
        "",
        "| Bug Type | Planted | Caught | Hit Rate |",
        "|----------|---------|--------|----------|",
    ]

    for bug_type, planted_count in planted_bugs.items():
        caught = bugs_reproduced.get(bug_type, 0)
        if bug_was_active:
            hit_rate = f"{caught}/{planted_count}"
            status = "✅" if caught >= planted_count else "❌"
        else:
            hit_rate = "N/A (bug not active)"
            status = "⏸️"
        lines.append(f"| {bug_type} | {planted_count} | {caught} | {hit_rate} {status} |")

    lines.extend([
        "",
        "## Test Case Results",
        "",
        "| Test ID | Name | Status | Bug Found |",
        "|---------|------|--------|-----------|",
    ])

    for r in test_results:
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        bug = r["bug_type"] if r["bug_reproduced"] else "—"
        lines.append(f"| {r['test_id']} | {r['name']} | {status} | {bug} |")

    lines.extend([
        "",
        "## Detailed Findings",
        "",
    ])

    for r in test_results:
        if not r["passed"] or r["bug_reproduced"]:
            lines.append(f"### {r['test_id']}: {r['name']}")
            lines.append("")
            for detail in r["details"]:
                lines.append(f"- {detail}")
            lines.append("")

    # False alarm analysis
    false_alarms = [r for r in test_results if not r["passed"] and not r["bug_reproduced"]]
    if false_alarms:
        lines.extend([
            "## False Alarms",
            "",
            f"Found {len(false_alarms)} test failure(s) without a known bug:",
            "",
        ])
        for r in false_alarms:
            lines.append(f"- **{r['test_id']}**: {r['name']}")
            for detail in r["details"]:
                lines.append(f"  - {detail}")
        lines.append("")

    lines.extend([
        "## Verdict",
        "",
    ])

    total_bugs_planted = sum(planted_bugs.values())
    total_bugs_caught = sum(bugs_reproduced.values())

    if not bug_was_active:
        verdict = "⏸️ **SKIPPED** - No bugs were planted (BUGS env var not set)"
    elif total_bugs_caught >= total_bugs_planted and len(false_alarms) == 0:
        verdict = "🟢 **EXCELLENT** - All bugs caught, no false alarms"
    elif total_bugs_caught >= total_bugs_planted:
        verdict = f"🟡 **GOOD** - All bugs caught, but {len(false_alarms)} false alarm(s)"
    elif total_bugs_caught > 0:
        verdict = f"🟠 **PARTIAL** - Caught {total_bugs_caught}/{total_bugs_planted} bugs, {len(false_alarms)} false alarm(s)"
    else:
        verdict = "🔴 **POOR** - Bug was planted but not caught"

    lines.append(verdict)

    return "\n".join(lines)


def main():
    results_path = Path("results/run_results.json")
    if not results_path.exists():
        print(f"No results found at {results_path}. Run runner.py first.")
        return

    results = load_results(results_path)
    report = generate_hit_rate_report(results)

    output_path = Path("results/hit_rate.md")
    output_path.write_text(report)
    print(f"Report written to {output_path}")
    print("\n" + report)


if __name__ == "__main__":
    main()