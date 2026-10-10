"""
Runner: deterministic test executor for three pillars.
- Functional: idempotency, balance conservation
- Performance: latency SLA
- Security: error leakage (PII/infrastructure)
"""
import time
import requests
from typing import Tuple

BASE_URL = "http://127.0.0.1:8000"

# ---------- Helper functions ----------
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
    return r.json().get("active_bugs", [])

def make_transfer(payload: dict, headers: dict) -> requests.Response:
    return requests.post(f"{BASE_URL}/transfer", json=payload, headers=headers, timeout=10)


# ---------- Pillar 1: Functional Tests ----------
def test_idempotency_retry() -> Tuple[bool, str]:
    """Pillar 1: Functional - Replay with same key must not double debit."""
    h = {"Idempotency-Key": f"retry-{time.time()}"}
    body = {"from_acc": "A", "to_acc": "B", "amount": 10_000}
    reset_bank()
    requests.post(f"{BASE_URL}/transfer", json=body, headers=h)
    requests.post(f"{BASE_URL}/transfer", json=body, headers=h)

    ledger = get_ledger()
    entries = [row for row in ledger if row["from"] == "A" and row["amount"] == 10_000]
    if len(entries) > 1:
        return False, "VIOLATION [double_charge]: Retried transfer created duplicate ledger records."
    return True, "Passed: Idempotent replay recorded once."

def test_balance_conservation() -> Tuple[bool, str]:
    """Pillar 1: Functional - Total balance before must equal total balance after."""
    h = {"Idempotency-Key": f"cons-{time.time()}"}
    reset_bank()
    b1_a = get_balance("A")
    b1_b = get_balance("B")

    requests.post(f"{BASE_URL}/transfer", json={"from_acc": "A", "to_acc": "B", "amount": 5_000}, headers=h)

    b2_a = get_balance("A")
    b2_b = get_balance("B")

    if (b1_a + b1_b) != (b2_a + b2_b):
        return False, "VIOLATION [phantom_success]: Balance destroyed; funds debited without crediting recipient."
    return True, "Passed: Balance strictly conserved."

def test_unknown_account_error() -> Tuple[bool, str]:
    """Pillar 1: Functional - Unknown account returns 404 without side effects."""
    h = {"Idempotency-Key": f"unknown-{time.time()}"}
    body = {"from_acc": "Z", "to_acc": "B", "amount": 1_000}
    reset_bank()
    before = get_balance("A")
    requests.post(f"{BASE_URL}/transfer", json=body, headers=h)
    after = get_balance("A")
    if after != before:
        return False, "VIOLATION: Unknown account request modified balances."
    return True, "Passed: Unknown account rejected safely."


# ---------- Pillar 2: Performance Tests ----------
def test_performance_sla(sla_ms: int = 400) -> Tuple[bool, str]:
    """Pillar 2: Performance - Latency SLA check."""
    h = {"Idempotency-Key": f"perf-{time.time()}"}
    body = {"from_acc": "A", "to_acc": "B", "amount": 1_000}
    reset_bank()

    t0 = time.perf_counter()
    requests.post(f"{BASE_URL}/transfer", json=body, headers=h)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    if elapsed_ms > sla_ms:
        return False, f"VIOLATION [latency_spike]: SLA breached. Response took {elapsed_ms:.1f}ms (threshold: {sla_ms}ms)."
    return True, f"Passed: Latency within SLA ({elapsed_ms:.1f}ms)."


# ---------- Pillar 3: Security Tests ----------
def test_security_leak() -> Tuple[bool, str]:
    """Pillar 3: Security - Error responses must not leak internal database infrastructure."""
    h = {"Idempotency-Key": "sec-test"}
    body = {"from_acc": "NONEXISTENT", "to_acc": "B", "amount": 1_000}
    reset_bank()
    res = requests.post(f"{BASE_URL}/transfer", json=body, headers=h)

    indicators = ["postgres", "cluster", "internal record", "stack trace", "za-central"]
    if any(token in res.text.lower() for token in indicators):
        return False, f"VIOLATION [pii_leak]: Response disclosed internal system infrastructure: {res.text.strip()}"
    return True, "Passed: Clean error response without infrastructure leaks."


# ---------- Suite ----------
def run_suite() -> list:
    tests = [
        ("tc-func-01", "Functional - Idempotency", test_idempotency_retry),
        ("tc-func-02", "Functional - Conservation", test_balance_conservation),
        ("tc-func-03", "Functional - Unknown Account", test_unknown_account_error),
        ("tc-perf-01", "Performance - Latency SLA", test_performance_sla),
        ("tc-sec-01",  "Security - Error Leakage", test_security_leak),
    ]

    results = []
    for test_id, name, fn in tests:
        passed, msg = fn()
        results.append({"id": test_id, "name": name, "passed": passed, "message": msg})
    return results


def main():
    # Verify bank is running
    try:
        requests.get(f"{BASE_URL}/ledger", timeout=2)
    except requests.exceptions.ConnectionError:
        print(f"Bank not running at {BASE_URL}. Start it with:")
        print("  uvicorn bank.app:app --port 8000")
        return

    print(f"Running {len(run_suite())} test cases...\n")
    for r in run_suite():
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        print(f"[{status}] {r['name']} ({r['id']}): {r['message']}")


if __name__ == "__main__":
    main()