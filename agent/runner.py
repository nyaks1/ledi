"""
Runner: deterministic test executor (no LLM calls).

Fires each test case against the bank, then decides pass/fail by READING THE
LEDGER AND BALANCES, never by trusting the HTTP status. Each violation is
labelled with a bug signature derived from *how* the rule broke:

  idem-001   ledger grew on a retry              -> "double_charge"
  ledger-001 sender and recipient deltas differ  -> "phantom_success"
  pii-001    long digit run in a response body   -> "pii_leak"

The runner never reads which bugs are planted. Only report/evaluate do.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8000"
LONG_DIGITS = re.compile(r"\d{8,}")  # account / ID / phone-like numbers


@dataclass
class TestResult:
    test_id: str
    name: str
    findings: list = field(default_factory=list)      # bug signatures (violations)
    observations: list = field(default_factory=list)  # needs human triage
    details: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "name": self.name,
            "passed": self.passed,
            "findings": sorted(set(self.findings)),
            "observations": self.observations,
            "details": self.details,
        }


# ---------- bank access (truth endpoints) ----------

def get_balance(acc: str) -> int:
    r = requests.get(f"{BASE_URL}/accounts/{acc}", timeout=5)
    r.raise_for_status()
    return r.json()["balance"]


def get_ledger() -> list:
    r = requests.get(f"{BASE_URL}/ledger", timeout=5)
    r.raise_for_status()
    return r.json()


def reset_bank() -> None:
    requests.post(f"{BASE_URL}/_test/reset", timeout=5).raise_for_status()


def get_active_bugs() -> list:
    r = requests.get(f"{BASE_URL}/_test/config", timeout=5)
    r.raise_for_status()
    return r.json()["active_bugs"]


def make_transfer(payload: dict, headers: dict) -> requests.Response:
    return requests.post(f"{BASE_URL}/transfer", json=payload, headers=headers, timeout=5)


def safe_json(resp: requests.Response):
    try:
        return resp.json()
    except ValueError:
        return resp.text


# ---------- invariant checks ----------
# Each returns (violation_signatures, detail_lines).

def check_idempotency(responses, ledger_snapshots):
    """Same key = same response and no new ledger entry on retry."""
    if len(responses) < 2:
        return [], ["only one request, idempotency check n/a"]
    sigs, details = [], []
    same = safe_json(responses[0]) == safe_json(responses[1])
    grew = len(ledger_snapshots[-1]) > len(ledger_snapshots[0])
    details.append(f"responses identical: {same}")
    details.append(
        f"ledger rows after 1st request: {len(ledger_snapshots[0])}, "
        f"after last retry: {len(ledger_snapshots[-1])}"
    )
    if grew:
        sigs.append("double_charge")
        details.append("VIOLATION: a retry with the same key created a new ledger entry")
    elif not same:
        sigs.append("unclassified")
        details.append("VIOLATION: retry returned a different response")
    return sigs, details


def check_ledger(payload, responses, repeat, before, after, rows_added):
    """200 => money moved consistently; failure => nothing moved."""
    sigs, details = [], []
    f, t, amount = payload["from_acc"], payload["to_acc"], payload["amount"]
    ok_count = sum(1 for r in responses if r.status_code == 200)

    if before is None:  # account not tracked (e.g. unknown account "Z")
        if ok_count == 0 and rows_added > 0:
            sigs.append("unclassified")
            details.append("VIOLATION: ledger grew although every request failed")
        return sigs, details

    sender_delta = before[f] - after[f]
    recipient_delta = after[t] - before[t]
    details.append(
        f"sender lost {sender_delta}, recipient gained {recipient_delta}, "
        f"ledger rows added {rows_added}, successes {ok_count}"
    )

    if ok_count == 0:
        if sender_delta != 0 or recipient_delta != 0 or rows_added != 0:
            sigs.append("unclassified")
            details.append("VIOLATION: money or ledger changed on a failed request")
        return sigs, details

    if sender_delta != recipient_delta:
        sigs.append("phantom_success")
        details.append("VIOLATION: sender and recipient amounts differ (money created or lost)")
    elif repeat == 1 and sender_delta != amount:
        sigs.append("unclassified")
        details.append(f"VIOLATION: expected exactly {amount} to move")
    if rows_added < 1:
        sigs.append("unclassified")
        details.append("VIOLATION: 200 OK but no ledger entry")
    return sigs, details


def check_pii(payload, headers, responses):
    """No long digit runs (account/ID-like) in any response we did not send ourselves."""
    sent = json.dumps(payload) + json.dumps(headers)
    sigs, details = [], []
    for i, r in enumerate(responses):
        for m in LONG_DIGITS.findall(r.text):
            if m in sent:
                continue  # echo of our own input, not a leak
            sigs.append("pii_leak")
            details.append(
                f"VIOLATION: response {i + 1} contains a {len(m)}-digit number (…{m[-2:]})"
            )
    return sigs, details


# ---------- one test case ----------

def run_test_case(tc: dict, verbose: bool = True) -> TestResult:
    test_id, name = tc["id"], tc["name"]
    payload = tc["payload"]
    headers = tc.get("headers", {})
    repeat = int(tc.get("repeat", 1))
    expected_status = tc.get("expected_status")
    wanted = set(tc.get("invariants_to_check", []))

    res = TestResult(test_id, name)
    reset_bank()  # isolation: every case starts from the same state

    tracked = ["A", "B"]
    before = {a: get_balance(a) for a in tracked}
    ledger_before = get_ledger()

    responses, snapshots = [], []
    for _ in range(repeat):
        resp = make_transfer(payload, headers)
        responses.append(resp)
        snapshots.append(get_ledger())

    after = {a: get_balance(a) for a in tracked}
    rows_added = len(get_ledger()) - len(ledger_before)

    # Expectation mismatch = the planner's guess differs from the bank.
    # It is NOT a verdict: a human decides whether the bank or the guess is wrong.
    for i, r in enumerate(responses):
        if expected_status is not None and r.status_code != expected_status:
            res.observations.append(
                f"request {i + 1}: expected {expected_status}, got {r.status_code}"
            )

    both_known = payload.get("from_acc") in before and payload.get("to_acc") in before
    bal_before = before if both_known else None

    checks = []
    # idempotency only makes sense for retries; ledger and PII run on EVERY case
    # because they are global rules, not optional ones.
    if repeat > 1 or "idem-001" in wanted:
        checks.append(("idem-001", check_idempotency(responses, snapshots)))
    checks.append(("ledger-001", check_ledger(payload, responses, repeat, bal_before, after, rows_added)))
    checks.append(("pii-001", check_pii(payload, headers, responses)))

    for inv_id, (sigs, details) in checks:
        res.findings.extend(sigs)
        res.details.extend(f"[{inv_id}] {d}" for d in details)

    if verbose:
        status = "PASS" if res.passed else "FAIL " + ",".join(sorted(set(res.findings)))
        print(f"  {test_id:8} {status:28} {name}")
        for o in res.observations:
            print(f"           note: {o}")
    return res


# ---------- suite ----------

def run_suite(test_cases: list, verbose: bool = True) -> dict:
    results = [run_test_case(tc, verbose) for tc in test_cases]
    return {
        "active_bugs": get_active_bugs(),
        "results": [r.to_dict() for r in results],
    }


def main():
    plan_path = Path("agent/test_plan.json")
    if not plan_path.exists():
        print("No agent/test_plan.json found. Run agent/planner.py first.")
        return
    cases = json.loads(plan_path.read_text())["test_cases"]
    try:
        requests.get(f"{BASE_URL}/ledger", timeout=2)
    except requests.exceptions.ConnectionError:
        print(f"Bank not running at {BASE_URL}. Start it in another terminal:")
        print("  uvicorn bank.app:app --port 8000")
        return

    print(f"Running {len(cases)} test cases...\n")
    out = run_suite(cases)
    failed = [r for r in out["results"] if not r["passed"]]
    found = sorted({s for r in failed for s in r["findings"]})
    print(f"\n{len(cases) - len(failed)}/{len(cases)} passed. Findings: {found or 'none'}")
    Path("results").mkdir(exist_ok=True)
    Path("results/last_run.json").write_text(json.dumps(out, indent=2))
    print("Saved results/last_run.json")


if __name__ == "__main__":
    main()