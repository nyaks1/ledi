"""
Report: renders results/evaluation.json into results/hit_rate.md.

Numbers are computed per scenario against what the bank says is planted
(GET /_test/config, captured by the runner). A bug counts once per scenario,
so the hit rate can never exceed 100%.
"""
import json
from pathlib import Path


def score(scenario: dict) -> dict:
    planted = set(scenario["active_bugs"])
    found = set()
    observations = []
    for r in scenario["results"]:
        found.update(r["findings"])
        for o in r["observations"]:
            observations.append((r["test_id"], r["name"], o))
    return {
        "name": scenario["name"],
        "planted": planted,
        "caught": planted & found,
        "missed": planted - found,
        "false_findings": found - planted,  # anything flagged that was not planted
        "observations": observations,
        "results": scenario["results"],
    }


def render(evaluation: dict) -> str:
    scores = [score(s) for s in evaluation["scenarios"]]
    planted_total = sum(len(s["planted"]) for s in scores)
    caught_total = sum(len(s["caught"]) for s in scores)
    false_total = sum(len(s["false_findings"]) for s in scores)
    clean = next((s for s in scores if not s["planted"]), None)

    L = [
        "# Hit Rate Report",
        "",
        f"Generated {evaluation['generated']} from **{evaluation['n_cases']} planner-written test cases "
        f"plus 1 built-in load check** "
        f"run against **{len(scores)} bank configurations**.",
        "",
        "## Headline",
        "",
        f"- **Planted bugs caught: {caught_total}/{planted_total}** "
        "(each bug counted once per scenario where it is planted)",
        f"- **False findings (flagged but not planted): {false_total}**",
    ]
    if clean is not None:
        L.append(
            f"- **Clean bank: {len(clean['results'])} cases, "
            f"{len(clean['false_findings'])} false findings**"
        )
    L += [
        "",
        "## Per scenario",
        "",
        "| Scenario | Planted | Caught | Missed | False findings | Cases failed |",
        "|---|---|---|---|---|---|",
    ]
    for s in scores:
        failed = sum(1 for r in s["results"] if not r["passed"])
        fmt = lambda x: ", ".join(sorted(x)) or "—"
        L.append(
            f"| {s['name']} | {fmt(s['planted'])} | {fmt(s['caught'])} | "
            f"{fmt(s['missed'])} | {fmt(s['false_findings'])} | {failed}/{len(s['results'])} |"
        )

    L += ["", "## Evidence: how each bug was caught", ""]
    for s in scores:
        if len(s["planted"]) != 1:
            continue
        L.append(f"### {next(iter(s['planted']))}")
        for r in s["results"]:
            if r["passed"]:
                continue
            L.append(f"- **{r['test_id']}** {r['name']}")
            for d in r["details"]:
                if "VIOLATION" in d:
                    L.append(f"  - {d}")
        L.append("")

    obs = [(s["name"], *o) for s in scores for o in s["observations"]]
    clean_obs = [o for o in obs if o[0].startswith("clean")]
    L += ["## Needs human triage (expectation mismatches)", ""]
    if clean_obs:
        L.append(
            "On the **clean** bank the planner's expected status differed from the "
            "bank's actual status. Either the planner guessed wrong or the bank has a "
            "real validation gap. Each one needs a human decision:"
        )
        L.append("")
        for _, tid, name, o in clean_obs:
            L.append(f"- {tid} {name}: {o}")
    else:
        L.append("None on the clean bank.")

    L += [
        "",
        "## Limits (read before trusting the numbers)",
        "",
        "- The four bug classes and the rules were designed together by the author, "
        "so a high catch rate shows the pipeline works, not that it generalises to unknown bugs.",
        "- Performance coverage is basic: a per-request latency budget and one burst of "
        "parallel transfers on a local fake bank. It is not a substitute for real load testing "
        "against production-like infrastructure.",
        "- The bank is a small in-memory fake with test-only endpoints (`/ledger`, "
        "`/accounts/{id}`). A real bank would need an equivalent read-only audit view.",
        "- All data is synthetic. No personal information is stored or sent anywhere.",
        "",
    ]
    return "\n".join(L)


def main():
    p = Path("results/evaluation.json")
    if not p.exists():
        print("No results/evaluation.json. Run agent/evaluate.py first.")
        return
    md = render(json.loads(p.read_text()))
    Path("results/hit_rate.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
