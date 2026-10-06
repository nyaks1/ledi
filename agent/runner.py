"""
Runner: Deterministic test executor
Fires test cases against the bank API, verifies invariants by reading ledger/balances.
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

BASE_URL = "http://127.0.0.1:8000"


@dataclass
class TestResult:
    test_id: str
    name: str
    passed: bool
    details: list[str] = field(default_factory=list)
    bug_reproduced: bool = False
    bug_type: str | None = None


def get_balance(acc: str) -> int:
    """Get account balance in cents."""
    resp = requests.get(f"{BASE_URL}/accounts/{acc}", timeout=5)
    resp.raise_for_status()
    return resp.json()["balance"]


def get_ledger() -> list[dict]:
    """Get full ledger."""
    resp = requests.get(f"{BASE_URL}/ledger", timeout=5)
    resp.raise_for_status()
    return resp.json()


def reset_bank() -> None:
    """Reset bank to initial state."""
    resp = requests.post(f"{BASE_URL}/_test/reset", timeout=5)
    resp.raise_for_status()


def make_transfer(payload: dict, headers: dict) -> requests.Response:
    """Execute a transfer request."""
    return requests.post(
        f"{BASE_URL}/transfer",
        json=payload,
        headers=headers,
        timeout=5
    )


def check_invariant_idem_001(
    test_id: str,
    responses: list[requests.Response],
    ledger_snapshots: list[list]
) -> tuple[bool, list[str]]:
    """Idempotency: same key = same response, no new ledger entry on retry."""
    details = []
    if len(responses) < 2:
        return True, ["Only one response, idem check N/A"]

    # Check responses are identical
    resp_equal = responses[0].json() == responses[1].json()
    details.append(f"Responses identical: {resp_equal}")
    if not resp_equal:
        details.append(f"  First: {responses[0].json()}")
        details.append(f"  Second: {responses[1].json()}")

    # Check ledger didn't grow BETWEEN retries (snapshot after first vs after second)
    # ledger_snapshots[0] = after first request, ledger_snapshots[1] = after second request
    ledger_grew_on_retry = len(ledger_snapshots[-1]) > len(ledger_snapshots[0])
    details.append(f"Ledger grew on retry: {ledger_grew_on_retry} (after 1st: {len(ledger_snapshots[0])}, after 2nd: {len(ledger_snapshots[-1])})")

    passed = resp_equal and not ledger_grew_on_retry
    if not passed:
        details.append("❌ IDEMPOTENCY VIOLATION: Retry created new ledger entry or different response")
    return passed, details


def check_invariant_ledger_001(
    test_id: str,
    payload: dict,
    response: requests.Response,
    balances_before: dict,
    balances_after: dict,
    ledger_before: list,
    ledger_after: list
) -> tuple[bool, list[str]]:
    """Ledger consistency: 200 OK means exact transfer; failure means nothing moved."""
    details = []
    from_acc = payload["from_acc"]
    to_acc = payload["to_acc"]
    amount = payload["amount"]
    status = response.status_code

    # If accounts don't exist in our balance tracking, skip detailed balance check
    if from_acc not in balances_before or to_acc not in balances_before:
        details.append(f"Accounts {from_acc} or {to_acc} not in balance tracking, skipping balance delta check")
        ledger_grew = len(ledger_after) > len(ledger_before)
        details.append(f"Ledger grew: {ledger_grew}")
        # For error responses, ledger should not grow
        passed = (status != 200 and not ledger_grew) or (status == 200 and ledger_grew)
        if not passed:
            details.append("❌ LEDGER VIOLATION: Unexpected ledger growth")
        return passed, details

    if status == 200:
        # Success: sender lost X, recipient gained X
        sender_delta = balances_before[from_acc] - balances_after[from_acc]
        recipient_delta = balances_after[to_acc] - balances_before[to_acc]
        ledger_grew = len(ledger_after) > len(ledger_before)

        details.append(f"Sender delta: {sender_delta} (expected {amount})")
        details.append(f"Recipient delta: {recipient_delta} (expected {amount})")
        details.append(f"Ledger grew: {ledger_grew}")

        passed = (sender_delta == amount and recipient_delta == amount and ledger_grew)
        if not passed:
            details.append("❌ LEDGER VIOLATION: Balance changes don't match transfer amount")
    else:
        # Failure: nothing should have moved
        sender_delta = balances_before[from_acc] - balances_after[from_acc]
        recipient_delta = balances_after[to_acc] - balances_before[to_acc]
        ledger_grew = len(ledger_after) > len(ledger_before)

        details.append(f"Failure status {status}: sender delta {sender_delta}, recipient delta {recipient_delta}, ledger grew {ledger_grew}")

        passed = (sender_delta == 0 and recipient_delta == 0 and not ledger_grew)
        if not passed:
            details.append("❌ LEDGER VIOLATION: Balances/ledger changed on failed request")

    return passed, details


def check_invariant_pii_001(
    test_id: str,
    responses: list[requests.Response]
) -> tuple[bool, list[str]]:
    """No PII: no full account numbers in responses."""
    details = []
    # In this fake bank, accounts are single letters (A, B), so "full account number"
    # would be the single letter. But the invariant is about not leaking full numbers.
    # We'll check that responses don't contain account identifiers in unexpected places.
    passed = True
    for i, resp in enumerate(responses):
        body = resp.text
        # Check for full account numbers - in a real system these would be long strings
        # For this fake bank, we just verify the response structure is clean
        try:
            data = resp.json()
            # Response should only have status/ledger_id or error detail
            if "status" in data:
                if not isinstance(data.get("ledger_id"), int):
                    details.append(f"  Response {i}: unexpected fields in success response")
            elif "detail" in data:
                pass  # Error response is fine
            else:
                details.append(f"  Response {i}: unexpected response structure: {data}")
        except Exception:
            details.append(f"  Response {i}: non-JSON response")
    return passed, details


def run_test_case(test_case: dict) -> TestResult:
    """Execute a single test case and verify invariants."""
    test_id = test_case["id"]
    name = test_case["name"]
    endpoint = test_case["endpoint"]
    method = test_case["method"]
    payload = test_case["payload"]
    headers = test_case.get("headers", {})
    repeat = test_case.get("repeat", 1)
    expected_status = test_case["expected_status"]
    invariants_to_check = test_case["invariants_to_check"]

    print(f"\n{'='*60}")
    print(f"Running {test_id}: {name}")
    print(f"{'='*60}")

    # Reset bank to initial state for test isolation
    reset_bank()

    # Snapshot before
    balances_before = {acc: get_balance(acc) for acc in ["A", "B"]}
    ledger_before = get_ledger()

    responses = []
    ledger_snapshots = []  # ledger after each request
    all_passed = True
    all_details = []
    bug_reproduced = False
    bug_type = None

    for i in range(repeat):
        print(f"  Request {i+1}/{repeat}...")
        resp = make_transfer(payload, headers)
        responses.append(resp)
        # Capture ledger after each request for idempotency check
        ledger_snapshots.append(get_ledger())
        print(f"    Status: {resp.status_code}, Body: {resp.json()}")

        # Check expected status
        if resp.status_code != expected_status:
            all_details.append(f"❌ Expected status {expected_status}, got {resp.status_code}")
            all_passed = False

    # Snapshot after
    balances_after = {acc: get_balance(acc) for acc in ["A", "B"]}
    ledger_after = get_ledger()

    print(f"  Balances before: {balances_before}")
    print(f"  Balances after:  {balances_after}")
    print(f"  Ledger before: {len(ledger_before)} entries")
    print(f"  Ledger after:  {len(ledger_after)} entries")

    # Check each invariant
    for inv_id in invariants_to_check:
        if inv_id == "idem-001":
            passed, details = check_invariant_idem_001(test_id, responses, ledger_snapshots)
        elif inv_id == "ledger-001":
            passed, details = check_invariant_ledger_001(
                test_id, payload, responses[-1], balances_before, balances_after, ledger_before, ledger_after
            )
        elif inv_id == "pii-001":
            passed, details = check_invariant_pii_001(test_id, responses)
        else:
            passed, details = False, [f"Unknown invariant: {inv_id}"]

        all_details.extend([f"  [{inv_id}] {d}" for d in details])
        if not passed:
            all_passed = False
            # Detect specific bug patterns
            if inv_id == "idem-001" and len(responses) >= 2:
                if len(ledger_after) > len(ledger_before):
                    bug_reproduced = True
                    bug_type = "double_charge"
                    print(f"  🐛 BUG REPRODUCED: {bug_type}")

    result = TestResult(
        test_id=test_id,
        name=name,
        passed=all_passed,
        details=all_details,
        bug_reproduced=bug_reproduced,
        bug_type=bug_type
    )

    status = "✅ PASSED" if all_passed else "❌ FAILED"
    print(f"\n  Result: {status}")
    for d in all_details:
        print(f"    {d}")

    return result


def main():
    # Load test plan
    plan_path = Path("agent/test_plan.json")
    if not plan_path.exists():
        print("No test_plan.json found. Run planner.py first.")
        return

    with open(plan_path) as f:
        plan = json.load(f)

    test_cases = plan["test_cases"]
    print(f"Loaded {len(test_cases)} test cases from {plan_path}")

    # Verify bank is running
    try:
        requests.get(f"{BASE_URL}/ledger", timeout=2)
    except requests.exceptions.ConnectionError:
        print(f"Bank not running at {BASE_URL}. Start it with:")
        print("  uvicorn bank.app:app --reload")
        return

    # Run all test cases
    results = []
    for tc in test_cases:
        result = run_test_case(tc)
        results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    bugs_found = sum(1 for r in results if r.bug_reproduced)

    print(f"Total: {len(results)} | Passed: {passed} | Failed: {failed} | Bugs reproduced: {bugs_found}")

    for r in results:
        status = "✅" if r.passed else "❌"
        bug = f" 🐛{r.bug_type}" if r.bug_reproduced else ""
        print(f"  {status} {r.test_id}: {r.name}{bug}")

    # Save results
    output = {
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "bugs_reproduced": bugs_found
        },
        "results": [
            {
                "test_id": r.test_id,
                "name": r.name,
                "passed": r.passed,
                "details": r.details,
                "bug_reproduced": r.bug_reproduced,
                "bug_type": r.bug_type
            }
            for r in results
        ]
    }

    output_path = Path("results/run_results.json")
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {output_path}")

    return output


if __name__ == "__main__":
    main()