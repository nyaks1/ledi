"""
Report: dynamically queries /_test/config for ground truth,
runs the suite, and generates a real scorecard.
"""
import requests
from agent.runner import run_suite

BASE_URL = "http://127.0.0.1:8000"


def generate_report():
    # Get ground truth from bank
    cfg = requests.get(f"{BASE_URL}/_test/config", timeout=5).json()
    planted = set(cfg.get("active_bugs", []))

    # Run test suite
    results = run_suite()
    detected = set()

    for r in results:
        if not r["passed"]:
            for b in ["double_charge", "phantom_success", "latency_spike", "pii_leak"]:
                if f"[{b}]" in r["message"]:
                    detected.add(b)

    tp = detected.intersection(planted)
    fp = detected - planted
    hit_rate = (len(tp) / len(planted)) * 100 if planted else 100.0

    md = f"""# QE Evaluation Report

- **Active Planted Invariants:** {', '.join(planted) if planted else 'None (Clean Baseline)'}
- **Detected Invariants:** {', '.join(detected) if detected else 'None'}
- **Hit Rate:** {hit_rate:.1f}% ({len(tp)}/{len(planted)})
- **False Alarms:** {len(fp)}

## Test Suite Execution Log:
"""
    for r in results:
        status = "PASSED" if r["passed"] else "VIOLATION"
        md += f"- **[{status}]** {r['name']} ({r['id']}): {r['message']}\n"

    with open("results/hit_rate.md", "w") as f:
        f.write(md)
    print(md)


if __name__ == "__main__":
    generate_report()