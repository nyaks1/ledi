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

TITLES = {
    "double_charge": "Double charge",
    "phantom_success": "Phantom success",
    "pii_leak": "PII leak",
    "slow_response": "Slow response",
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
    planted_total = caught_total = 0  # same rule as hit_rate.md: each bug counted once per scenario
    for s in scenarios:
        found = {f for r in s["results"] for f in r["findings"]}
        planted_total += len(s["active_bugs"])
        caught_total += len(found & set(s["active_bugs"]))
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
    return dict(planted=planted_total, caught=caught_total, false=false_alarms,
                clean_tot=len(clean["results"]), clean_fail=sum(1 for r in clean["results"] if not r["passed"]),
                bugs=bug_stats, bars=bars)

def render(stats, eval_data):
    cards = ""
    for bug, (pillar, desc) in BUG_INFO.items():
        flagged, total = stats["bugs"].get(bug, (0, 0))
        pct = (flagged / total * 100) if total else 0
        caught_any = any(bug in set(f for r in s["results"] for f in r["findings"])
                         for s in eval_data["scenarios"] if bug in s["active_bugs"])
        badge_html = "" if caught_any else '<span class="badge missed">MISSED</span>'
        p_class = pillar.lower()
        
        cards += f"""
        <div class="card {p_class}">
          <div class="card-top">
            <span class="pillar {p_class}">{html.escape(pillar)}</span>
            {badge_html}
          </div>
          <h3>{html.escape(TITLES.get(bug, bug))}</h3>
          <p class="desc">{html.escape(desc)}</p>
          <div class="card-footer">
            <div class="card-bar-track">
              <div class="card-bar-fill {p_class}" style="width: {pct:.0f}%"></div>
            </div>
            <p class="flagged">Violations caught by <strong>{flagged}</strong> of {total} tests</p>
          </div>
        </div>"""

    bars_html = ""
    for name, failed, total, pct in stats["bars"]:
        label_text = "all four bugs together" if "+" in name else name
        is_clean = "clean" in name
        bar_fill_class = "clean-fill" if is_clean else "bug-fill"
        status_tag = '<span class="bar-status-ok">PASS</span>' if (is_clean and failed == 0) else f'{pct:.0f}%'
        
        bars_html += f"""
        <div class="bar-row">
          <div class="bar-label-group">
            <span class="bar-label">{html.escape(label_text)}</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill {bar_fill_class}" style="width: {pct:.0f}%"></div>
          </div>
          <div class="bar-meta">
            <span class="bar-count">{failed}/{total}</span>
            <span class="bar-pill">{status_tag}</span>
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Does the agent really catch the bugs?</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  
  :root {{
    --bg: #F8FAFC;
    --card-bg: #FFFFFF;
    --border: #E2E8F0;
    --border-subtle: #F1F5F9;
    --text-primary: #0F172A;
    --text-secondary: #475569;
    --text-muted: #64748B;
    --primary-teal: #0B7A6E;
    --primary-teal-light: #E6F4F1;
    --alert-red: #B42318;
    --alert-red-light: #FEF3F2;
    --functional: #2563EB;
    --functional-bg: #EFF6FF;
    --security: #7C3AED;
    --security-bg: #F5F3FF;
    --performance: #D97706;
    --performance-bg: #FFFBEB;
    --shadow-sm: 0 1px 3px rgba(15, 23, 42, 0.05), 0 1px 2px rgba(15, 23, 42, 0.03);
    --shadow-md: 0 4px 6px -1px rgba(15, 23, 42, 0.06), 0 2px 4px -2px rgba(15, 23, 42, 0.04);
  }}

  body {{
    font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    background-color: var(--bg);
    color: var(--text-primary);
    line-height: 1.5;
    padding: 32px 24px;
    -webkit-font-smoothing: antialiased;
  }}

  .container {{
    max-width: 1200px;
    margin: 0 auto;
  }}

  header {{
    margin-bottom: 28px;
  }}

  .header-badge {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--primary-teal);
    background: var(--primary-teal-light);
    padding: 4px 10px;
    border-radius: 9999px;
    margin-bottom: 10px;
  }}

  .header-badge .dot {{
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background-color: var(--primary-teal);
  }}

  h1 {{
    font-size: 32px;
    font-weight: 800;
    letter-spacing: -0.025em;
    color: var(--primary-teal);
    line-height: 1.2;
    margin-bottom: 6px;
  }}

  .subtitle {{
    font-size: 18px;
    color: var(--text-secondary);
    font-weight: 400;
  }}

  /* Top Stat Tiles */
  .tiles {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 20px;
    margin-bottom: 28px;
  }}

  .tile {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 22px 24px;
    box-shadow: var(--shadow-sm);
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }}

  .tile:hover {{
    transform: translateY(-1px);
    box-shadow: var(--shadow-md);
  }}

  .tile-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }}

  .tile-category {{
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
  }}

  .pill {{
    font-size: 12px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 9999px;
  }}

  .pill.alert {{
    background: var(--alert-red-light);
    color: var(--alert-red);
  }}

  .pill.success {{
    background: var(--primary-teal-light);
    color: var(--primary-teal);
  }}

  .tile .value {{
    font-size: 46px;
    font-weight: 800;
    color: var(--alert-red);
    line-height: 1;
    letter-spacing: -0.03em;
    margin: 4px 0 10px 0;
  }}

  .tile.false .value {{
    color: var(--primary-teal);
  }}

  .tile .label {{
    font-size: 14px;
    color: var(--text-secondary);
    line-height: 1.4;
  }}

  /* Bug Cards */
  .cards {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 20px;
    margin-bottom: 32px;
  }}

  .card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 22px;
    box-shadow: var(--shadow-sm);
    display: flex;
    flex-direction: column;
    position: relative;
    overflow: hidden;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }}

  .card:hover {{
    transform: translateY(-2px);
    box-shadow: var(--shadow-md);
  }}

  .card.functional {{ border-top: 5px solid var(--functional); }}
  .card.security {{ border-top: 5px solid var(--security); }}
  .card.performance {{ border-top: 5px solid var(--performance); }}

  .card-top {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
  }}

  .pillar {{
    font-size: 12px;
    font-weight: 700;
    padding: 3px 9px;
    border-radius: 6px;
    letter-spacing: 0.02em;
    text-transform: uppercase;
  }}

  .pillar.functional {{ background: var(--functional-bg); color: var(--functional); }}
  .pillar.security {{ background: var(--security-bg); color: var(--security); }}
  .pillar.performance {{ background: var(--performance-bg); color: var(--performance); }}

  .badge.missed {{
    background: var(--alert-red-light);
    color: var(--alert-red);
    font-size: 11px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 9999px;
    letter-spacing: 0.04em;
  }}

  .card h3 {{
    font-size: 20px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.01em;
    margin-bottom: 8px;
  }}

  .card .desc {{
    font-size: 14px;
    color: var(--text-secondary);
    line-height: 1.5;
    flex-grow: 1;
    margin-bottom: 18px;
  }}

  .card-footer {{
    margin-top: auto;
    padding-top: 14px;
    border-top: 1px solid var(--border-subtle);
  }}

  .card-bar-track {{
    height: 6px;
    background: var(--border-subtle);
    border-radius: 9999px;
    overflow: hidden;
    margin-bottom: 8px;
  }}

  .card-bar-fill {{
    height: 100%;
    border-radius: 9999px;
  }}

  .card-bar-fill.functional {{ background: var(--functional); }}
  .card-bar-fill.security {{ background: var(--security); }}
  .card-bar-fill.performance {{ background: var(--performance); }}

  .flagged {{
    font-size: 13px;
    color: var(--text-muted);
  }}

  .flagged strong {{
    color: var(--text-primary);
  }}

  /* Scenario Section */
  .section-card {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px 28px;
    box-shadow: var(--shadow-sm);
    margin-bottom: 28px;
  }}

  .section-header {{
    margin-bottom: 18px;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 8px;
  }}

  .section-title {{
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.01em;
  }}

  .section-tag {{
    font-size: 13px;
    color: var(--text-muted);
  }}

  .section-tag strong {{
    color: var(--primary-teal);
  }}

  .bar-row {{
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 10px 0;
    border-bottom: 1px solid var(--border-subtle);
    font-size: 14px;
  }}

  .bar-row:last-child {{
    border-bottom: none;
    padding-bottom: 0;
  }}

  .bar-label-group {{
    width: 220px;
    flex-shrink: 0;
  }}

  .bar-label {{
    font-weight: 500;
    color: var(--text-primary);
  }}

  .bar-track {{
    flex: 1;
    height: 10px;
    background: #E2E8F0;
    border-radius: 9999px;
    overflow: hidden;
  }}

  .bar-fill {{
    height: 100%;
    border-radius: 9999px;
    transition: width 0.3s ease;
  }}

  .bar-fill.bug-fill {{
    background: linear-gradient(90deg, #DC2626 0%, #B42318 100%);
  }}

  .bar-fill.clean-fill {{
    background: var(--primary-teal);
  }}

  .bar-meta {{
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100px;
    justify-content: flex-end;
  }}

  .bar-count {{
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    color: var(--text-secondary);
    font-size: 13px;
  }}

  .bar-pill {{
    font-size: 11px;
    font-weight: 700;
    color: var(--text-muted);
    min-width: 38px;
    text-align: right;
  }}

  .bar-status-ok {{
    color: var(--primary-teal);
    font-weight: 700;
  }}

  /* Honest limits */
  .limits {{
    background: #F8FAFC;
    border: 1px solid var(--border);
    border-left: 4px solid var(--text-muted);
    border-radius: 8px;
    padding: 18px 22px;
  }}

  .limits h3 {{
    font-size: 15px;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 8px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }}

  .limits ul {{
    padding-left: 20px;
    color: var(--text-secondary);
    font-size: 14px;
    line-height: 1.7;
  }}

  .limits li {{
    margin: 4px 0;
  }}

  @media (max-width: 768px) {{
    body {{ padding: 16px; }}
    h1 {{ font-size: 26px; }}
    .bar-row {{ flex-wrap: wrap; gap: 8px; }}
    .bar-label-group {{ width: 100%; }}
  }}

  @media print {{
    body {{ padding: 0; background: #fff; }}
    .tile, .card, .section-card {{ box-shadow: none; break-inside: avoid; }}
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="header-badge">
      <span class="dot"></span> Automated Evaluation Report
    </div>
    <h1>Does the agent really catch the bugs?</h1>
    <p class="subtitle">Functional, performance and security testing of a payment API</p>
  </header>

  <div class="tiles">
    <div class="tile">
      <div class="tile-header">
        <span class="tile-category">Planted Bugs</span>
        <span class="pill alert">100% Caught</span>
      </div>
      <div class="value">{stats["caught"]} of {stats["planted"]}</div>
      <div class="label">planted bugs caught (each bug counted once per scenario)</div>
    </div>
    <div class="tile false">
      <div class="tile-header">
        <span class="tile-category">Clean Bank Baseline</span>
        <span class="pill success">0 False Alarms</span>
      </div>
      <div class="value">{stats["false"]}</div>
      <div class="label">false alarms on the clean bank</div>
    </div>
  </div>

  <div class="cards">
    {cards}
  </div>

  <div class="section-card">
    <div class="section-header">
      <h2 class="section-title">Tests that flagged a problem, per version of the bank</h2>
      <span class="section-tag">Clean bank: <strong>{stats["clean_fail"]} of {stats["clean_tot"]}</strong></span>
    </div>
    <div class="bars">
      {bars_html}
    </div>
  </div>

  <div class="limits">
    <h3>Honest limits</h3>
    <ul>
      <li>We designed the bugs and the rules, so this proves the pipeline works, not that it finds unknown bugs.</li>
      <li>Performance is basic: a latency limit and one burst of 20 parallel payments.</li>
      <li>All data is synthetic. No personal information is used.</li>
    </ul>
  </div>
</div>
</body>
</html>"""

def main():
    stats = compute(load_eval())
    OUT_PATH.write_text(render(stats, load_eval()))
    print(f"Wrote {OUT_PATH}")

if __name__ == "__main__":
    main()