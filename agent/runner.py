"""
Runner: Deterministic test executor
Fires test cases against the bank API, verifies invariants by reading ledger/balances.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    bug_types: list[str] = field(default_factory=list)


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


def get_active_bugs() -> list[str]:
    """Get list of active bugs from bank."""
    try:
        resp = requests.get(f"{BASE_URL}/_test/config", timeout=5)
        resp.raise_for_status()
        return resp.json().get("active_bugs", [])
    except Exception:
        return []


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
        passed = (status != 200 and not ledger_grew) or (status == 200 and ledger_grew)
        if not passed:
            details.append("❌ LEDGER VIOLATION: Unexpected ledger growth")
        return passed, details

    # Self-transfer: from_acc == to_acc, balance should not change
    is_self_transfer = (from_acc == to_acc)

    if status == 200:
        # Success: sender lost X, recipient gained X (unless self-transfer)
        sender_delta = balances_before[from_acc] - balances_after[from_acc]
        recipient_delta = balances_after[to_acc] - balances_before[to_acc]
        ledger_grew = len(ledger_after) > len(ledger_before)

        if is_self_transfer:
            details.append(f"Self-transfer: sender delta {sender_delta}, recipient delta {recipient_delta}, ledger grew {ledger_grew}")
            # For self-transfer, balance should not change, ledger may or may not grow
            passed = (sender_delta == 0 and recipient_delta == 0)
            if not passed:
                details.append("❌ SELF-TRANSFER VIOLATION: Balance changed on self-transfer")
        else:
            details.append(f"Sender delta: {sender_delta} (expected {amount})")
            details.append(f"Recipient delta: {recipient_delta} (expected {amount})")
            details.append(f"Ledger grew: {ledger_grew}")

            # Check for phantom_success: ledger grew but recipient didn't gain
            if ledger_grew and sender_delta == amount and recipient_delta != amount:
                details.append("❌ PHANTOM SUCCESS: Ledger entry exists but recipient not credited")

            passed = (sender_delta == amount and recipient_delta == amount and ledger_grew)
            if not passed and not (ledger_grew and sender_delta == amount and recipient_delta != amount):
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
    passed = True
    # Known synthetic account numbers (10-digit strings)
    synthetic_accounts = {"1234567890", "0987654321"}
    # Also check for short account IDs inappropriately exposed
    short_accounts = {"A", "B", "Z"}
    
    for i, resp in enumerate(responses):
        body = resp.text
        data = resp.json()
        
        # Check error responses for leaked account numbers
        if "detail" in data:
            detail = str(data["detail"])
            # Check for synthetic full account numbers (10+ digit strings)
            for acc in synthetic_accounts:
                if acc in detail:
                    passed = False
                    details.append(f"  Response {i}: PII LEAK in error - '{detail}' (contains synthetic account {acc})")
            # Check for short account IDs exposed beyond generic messages
            for acc in short_accounts:
                if acc in detail and detail not in ("unknown account", "invalid amount"):
                    if len(detail) > 20:  # More than generic message
                        passed = False
                        details.append(f"  Response {i}: PII LEAK in error - '{detail}' (contains account {acc})")
        
        # Check success responses for unexpected fields
        if "status" in data:
            unexpected = set(data.keys()) - {"status", "ledger_id", "phantom"}
            if unexpected:
                details.append(f"  Response {i}: unexpected fields in success response: {unexpected}")
    
    if passed:
        details.append("No PII detected in responses")
    return passed, details


def run_concurrent_transfers(payload: dict, headers: dict, count: int) -> list[requests.Response]:
    """Execute transfers concurrently using threads."""
    responses = [None] * count
    
    def make_request(index: int):
        responses[index] = make_transfer(payload, headers)
    
    with ThreadPoolExecutor(max_workers=count) as executor:
        futures = [executor.submit(make_request, i) for i in range(count)]
        for future in as_completed(futures):
            future.result()
    
    return responses


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
    concurrent = test_case.get("concurrent", False)

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
    bug_types = []

    if concurrent:
        # Run concurrent transfers
        print(f"  Running {repeat} concurrent requests...")
        responses = run_concurrent_transfers(payload, headers, repeat)
        for i, resp in enumerate(responses):
            print(f"    Request {i+1}: Status {resp.status_code}, Body: {resp.json()}")
            ledger_snapshots.append(get_ledger())
    else:
        # Run sequential requests
        for i in range(repeat):
            print(f"  Request {i+1}/{repeat}...")
            resp = make_transfer(payload, headers)
            responses.append(resp)
            ledger_snapshots.append(get_ledger())
            print(f"    Status: {resp.status_code}, Body: {resp.json()}")

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
                    if "double_charge" not in bug_types:
                        bug_types.append("double_charge")
                    print(f"  🐛 BUG REPRODUCED: double_charge")
            elif inv_id == "ledger-001":
                # Check for phantom_success pattern
                resp_data = responses[-1].json()
                if resp_data.get("phantom") or (resp_data.get("status") == "ok" and balances_after[payload["to_acc"]] == balances_before[payload["to_acc"]]):
                    bug_reproduced = True
                    if "phantom_success" not in bug_types:
                        bug_types.append("phantom_success")
                    print(f"  🐛 BUG REPRODUCED: phantom_success")
            elif inv_id == "pii-001":
                bug_reproduced = True
                if "pii_leak" not in bug_types:
                    bug_types.append("pii_leak")
                print(f"  🐛 BUG REPRODUCED: pii_leak")

    result = TestResult(
        test_id=test_id,
        name=name,
        passed=all_passed,
        details=all_details,
        bug_reproduced=bug_reproduced,
        bug_types=bug_types
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

    # Verify bank is running and get active bugs
    try:
        active_bugs = get_active_bugs()
        print(f"Bank active bugs: {active_bugs}")
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
        bug = f" 🐛{', '.join(r.bug_types)}" if r.bug_types else ""
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
                "bug_types": r.bug_types
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