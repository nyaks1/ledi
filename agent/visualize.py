#!/usr/bin/env python3
"""visualize.py - Generate a single-page HTML report from evaluation.json for hackathon judges. No external deps."""
import json, html, sys
from pathlib import Path

EVAL_PATH = Path("results/evaluation.json")
OUT_PATH = Path("results/report.html")

BUG_INFO = {
    "double_charge":   ("Functional", "Tap Pay twice, get charged twice"),
    "phantom_success": ("Functional", "Sender is charged, recipient never gets paid, bank still says OK"),
    "pii_leak":        ("Security",    "An error message shows a full account number"),
    "slow_response":   ("Performance", "Every payment takes almost a second, over the 500 ms limit"),
}

def load_eval():
    if not EVAL_PATH.exists():
        print(f"Missing {EVAL_PATH}. Run `python agent/evaluate.py` first.", file=sys.stderr)
        sys.exit(1)
    return json.loads(EVAL_PATH.read_text())

def compute(eval_data):
    scenarios = eval_data["scenarios"]
    clean = next(s for s in scenarios if not s["active_bugs"])
    all_planted = set()
    for s in scenarios:
        all_planted.update(s["active_bugs"])
    caught = set()
    for s in scenarios:
        if not s["active_bugs"]: continue
        found = set()
        for r in s["results"]:
            found.update(r["findings"])
        caught.update(found & set(s["active_bugs"]))
    false_alarms = sum(1 for r in clean["results"] for f in r["findings"])
    bug_stats = {}
    for bug in all_planted:
        solo = next((s for s in eval_data["scenarios"] if s["active_bugs"] == [bug]), None)
        if solo:
            flagged = sum(1 for r in solo["results"] if bug in r["findings"])
            total = len(solo["results"])
        else:
            flagged = sum(1 for s in eval_data["scenarios"] if bug in s["active_bugs"] for r in s["results"] if bug in r["findings"])
            total = sum(len(s["results"]) for s in eval_data["scenarios"] if bug in s["active_bugs"])
        bug_stats[bug] = (flagged, total)
    bars = []
    for s in eval_data["scenarios"]:
        failed = sum(1 for r in s["results"] if not r["passed"])
        total = len(s["results"])
        bars.append((s["name"], failed, total, failed/total*100 if total else 0))
    return dict(planted=len(all_planted), caught=len(caught), false=false_alarms,
                clean_tot=len(clean["results"]), clean_fail=sum(1 for r in clean["results"] if not r["passed"]),
                bugs=bug_stats, bars=bars)

def render(stats, eval_data):
    cards = ""
    for bug, (pillar, desc) in BUG_INFO.items():
        flagged, total = stats["bugs"].get(bug, (0,0))
        caught_any = any(bug in set(f for r in s["results"] for f in r["findings"])
                         for s in eval_data["scenarios"] if bug in s["active_bugs"])
        badge = "caught" if caught_any else "missed"
        badge_txt = "CAUGHT" if caught_any else "MISSED"
        cards += f'<div class="card"><div class="badge {badge}">{badge_txt}</div><h3>{html.escape(bug)}</h3><span class="pillar">{html.escape(BUG_INFO[bug][0])}</span><p>{html.escape(desc)}</p><p class="flagged">flagged by {stats["bugs"][bug][0]} of {stats["bugs"][bug][1]} tests</p></div>'
    bars = "".join(f'<div class="bar-row"><span class="bar-label">{html.escape(n)}</span><div class="bar-track"><div class="bar-fill" style="width:{p:.0f}%"></div></div><span class="bar-count">{f}/{t}</span></div>' for n,f,t,p in stats["bars"])
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Does the agent really catch the bugs?</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}body{{font:20px/1.5 system-ui,-apple-system,sans-serif;background:#f8faf9;color:#1a1a1a;padding:24px;max-width:1920px;margin:0 auto}}h1{{font-size:32px;font-weight:700;color:#0B7A6E;margin-bottom:4px}}.subtitle{{font-size:20px;color:#444;margin-bottom:24px}}.tiles{{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}}.tile{{flex:1;min-width:200px;background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:16px 24px}}.tile .value{{font-size:48px;font-weight:700;color:#0B7A6E;line-height:1}}.tile .label{{font-size:16px;color:#666;margin-top:4px}}.tile.false .value{{color:#B42318}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-bottom:24px}}.card{{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:20px;position:relative}}.card h3{{font-size:22px;font-weight:600;margin-bottom:4px}}.pillar{{display:inline-block;font-size:13px;font-weight:600;padding:2px 8px;border-radius:4px;background:#e8f5e9;color:#0B7A6E;margin-bottom:8px}}.card p{{color:#333;margin:4px 0}}.flagged{{font-size:14px;color:#666;margin-top:8px!important}}.badge{{position:absolute;top:16px;right:16px;font-size:12px;font-weight:700;padding:4px 10px;border-radius:999px}}.badge.caught{{background:#e8f5e9;color:#0B7A6E}}.badge.missed{{background:#fdeaea;color:#B42318}}.bars{{margin-top:24px}}.bar-row{{display:flex;align-items:center;gap:12px;margin:8px 0;font-size:16px}}.bar-label{{width:180px;flex-shrink:0;color:#333}}.bar-track{{flex:1;height:16px;background:#e0e0e0;border-radius:8px;overflow:hidden}}.bar-fill{{height:100%;background:#B42318;border-radius:8px}}.bar-count{{width:70px;text-align:right;color:#666;font-variant-numeric:tabular-nums}}.limits{{margin-top:32px;padding:16px 20px;background:#fff;border:1px solid #e0e0e0;border-radius:8px;color:#444;font-size:16px}}.limits h3{{font-size:18px;margin-bottom:12px;color:#333}}.limits ul{{margin:0;padding-left:20px;line-height:1.8}}.limits li{{margin:4px 0}}@media print{{body{{padding:0}}.tile,.card{{break-inside:avoid}}}}</style></head><body>
<h1>Does the agent really catch the bugs?</h1><p class="subtitle">Functional, performance and security testing of a payment API</p>
<div class="tiles"><div class="tile"><div class="value">{stats["caught"]} of {stats["planted"]}</div><div class="label">planted bugs caught</div></div><div class="tile false"><div class="value">{stats["false"]}</div><div class="label">false alarms on the clean bank</div></div></div>
<div class="cards">{cards}</div>
<div class="bars"><h2 style="font-size:20px;margin-bottom:12px;color:#333">Clean bank: {stats["clean_tot"]} tests, {stats["clean_fail"]} failed</h2>{bars}</div>
<div class="limits"><h3>Honest limits</h3><ul><li>We designed the bugs and the rules, so this proves the pipeline works, not that it finds unknown bugs.</li><li>Performance is basic: a latency limit and one burst of 20 parallel payments.</li><li>All data is synthetic. No personal information is used.</li></ul></div></body></html>"""

def main():
    stats = compute(load_eval())
    OUT_PATH.write_text(render(stats, load_eval()))
    print(f"Wrote {OUT_PATH}")

if __name__ == "__main__":
    main()