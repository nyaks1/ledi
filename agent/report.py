"""
Report: Generates hit-rate table from test results
Shows bugs planted vs caught, false alarms
"""
import json
from pathlib import Path
from typing import Any

import requests


BASE_URL = "http://127.0.0.1:8000"


def get_active_bugs() -> list[str]:
    """Get list of active bugs from bank."""
    try:
        resp = requests.get(f"{BASE_URL}/_test/config", timeout=5)
        resp.raise_for_status()
        return resp.json().get("active_bugs", [])
    except Exception:
        return []


def load_results(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def generate_hit_rate_report(results: dict[str, Any], active_bugs: list[str]) -> str:
    """Generate markdown hit-rate report."""
    summary = results["summary"]
    test_results = results["results"]

    # Count bugs by type that were CAUGHT (distinct types)
    caught_bug_types = set()
    for r in test_results:
        if r["bug_reproduced"] and r.get("bug_types"):
            caught_bug_types.update(r["bug_types"])

    # Planted bugs come from the bank's config endpoint
    planted_bug_types = set(active_bugs)

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

    all_bug_types = planted_bug_types | caught_bug_types
    for bug_type in sorted(all_bug_types):
        planted = "✅" if bug_type in planted_bug_types else "❌"
        caught = "✅" if bug_type in caught_bug_types else "❌"
        
        if bug_type in planted_bug_types:
            hit_rate = "1/1" if bug_type in caught_bug_types else "0/1"
            status = "✅" if bug_type in caught_bug_types else "❌"
        else:
            hit_rate = "N/A (not planted)"
            status = "⚠️"
        lines.append(f"| {bug_type} | {planted} | {caught} | {hit_rate} {status} |")

    # Overall hit rate
    if planted_bug_types:
        overall_caught = len(planted_bug_types & caught_bug_types)
        overall_total = len(planted_bug_types)
        overall_rate = f"{overall_caught}/{overall_total}"
    else:
        overall_rate = "N/A (no bugs planted)"

    lines.extend([
        "",
        f"**Overall Hit Rate: {overall_rate}**",
        "",
        "## Test Case Results",
        "",
        "| Test ID | Name | Status | Bug Found |",
        "|---------|------|--------|-----------|",
    ])

    for r in test_results:
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        bug = ", ".join(r.get("bug_types", [])) if r["bug_reproduced"] else "—"
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

    # False alarm analysis: test failed but no known bug was caught
    false_alarms = [r for r in test_results if not r["passed"] and not r["bug_reproduced"]]
    if false_alarms:
        lines.extend([
            "## False Alarms",
            "",
            f"Found {len(false_alarms)} test failure(s) without a reproduced bug:",
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

    if not planted_bug_types:
        verdict = "⏸️ **SKIPPED** - No bugs were planted (BUGS env var not set)"
    elif len(planted_bug_types & caught_bug_types) == len(planted_bug_types) and len(false_alarms) == 0:
        verdict = "🟢 **EXCELLENT** - All planted bugs caught, no false alarms"
    elif len(planted_bug_types & caught_bug_types) == len(planted_bug_types):
        verdict = f"🟡 **GOOD** - All planted bugs caught, but {len(false_alarms)} false alarm(s)"
    elif len(planted_bug_types & caught_bug_types) > 0:
        verdict = f"🟠 **PARTIAL** - Caught {len(planted_bug_types & caught_bug_types)}/{len(planted_bug_types)} planted bug types, {len(false_alarms)} false alarm(s)"
    else:
        verdict = "🔴 **POOR** - Planted bugs not caught"

    lines.append(verdict)

    return "\n".join(lines)


def main():
    results_path = Path("results/run_results.json")
    if not results_path.exists():
        print(f"No results found at {results_path}. Run runner.py first.")
        return

    results = load_results(results_path)
    active_bugs = get_active_bugs()
    report = generate_hit_rate_report(results, active_bugs)

    output_path = Path("results/hit_rate.md")
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(report)
    print(f"Report written to {output_path}")
    print("\n" + report)


if __name__ == "__main__":
    main()