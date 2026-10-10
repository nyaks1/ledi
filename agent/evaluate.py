"""
Evaluate: the honest hit rate.

Starts the fake bank once per scenario (clean, each bug alone, all bugs), runs the
SAME test plan against each, and writes results/evaluation.json + results/hit_rate.md.

    python agent/evaluate.py
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report  # noqa: E402
import runner  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PORT = 8000
BASE = f"http://127.0.0.1:{PORT}"

SCENARIOS = [
    [],
    ["double_charge"],
    ["phantom_success"],
    ["pii_leak"],
    ["double_charge", "phantom_success", "pii_leak"],
]


def port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def start_bank(bugs: list) -> subprocess.Popen:
    # An old bank still holding the port would answer our health check and make
    # every scenario silently test the wrong bank. Refuse to run instead.
    if port_in_use():
        raise SystemExit(
            f"Port {PORT} is already in use, so this run would test the wrong bank.\n"
            "Stop it first:  pkill -f 'uvicorn bank.app'   then run this again."
        )
    env = {**os.environ, "BUGS": ",".join(bugs)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "bank.app:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=ROOT, env=env,
    )
    for _ in range(50):
        if proc.poll() is not None:
            raise SystemExit("The bank process exited immediately. Check your venv and that port 8000 is free.")
        try:
            requests.get(f"{BASE}/ledger", timeout=0.5)
            break
        except requests.exceptions.RequestException:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise SystemExit("The bank did not start within 10 seconds.")
    # Prove it is OUR bank, with exactly the bugs this scenario asked for.
    active = requests.get(f"{BASE}/_test/config", timeout=2).json()["active_bugs"]
    if active != sorted(bugs):
        proc.terminate()
        raise SystemExit(f"Bank reports bugs {active} but this scenario needs {sorted(bugs)}. Refusing to continue.")
    return proc


def main():
    plan = json.loads((ROOT / "agent" / "test_plan.json").read_text())
    cases = plan["test_cases"]
    scenarios = []
    for bugs in SCENARIOS:
        label = "+".join(bugs) if bugs else "clean (no bugs)"
        print(f"\n=== scenario: {label} ===")
        proc = start_bank(bugs)
        try:
            out = runner.run_suite(cases)
        finally:
            proc.terminate()
            proc.wait()
        out["name"] = label
        scenarios.append(out)

    evaluation = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_cases": len(cases),
        "scenarios": scenarios,
    }
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "evaluation.json").write_text(json.dumps(evaluation, indent=2))
    md = report.render(evaluation)
    (ROOT / "results" / "hit_rate.md").write_text(md)
    print("\n" + md)


if __name__ == "__main__":
    main()