# sebaka-agent

An AI agent for Software Quality Engineering (API testing, money-moving APIs).

> Status: **Complete** — fake bank, planner, runner, and reporter all working.

## Problem

Payment APIs fail in ways nobody wrote a test for. A test suite is a list of
what a human imagined, so the bug that escapes is the one nobody imagined.

## Villain

The untested gap between what an API promises and what it actually does.
Example: a phone drops signal, the backend charges, the client retries, and
the customer is charged twice.

## Hero

An agent that:
- **Receives** an OpenAPI spec.
- **Decides** which endpoints move money and which rules must always hold.
- **Does** fires edge cases and retries, then checks the ledger instead of
  trusting "200 OK".
- **Returns** only findings it reproduced, with the request sequence.

## Rules ("invariants") the agent checks

1. **Idempotency (idem-001)**: A retried request (same idempotency key) returns the same response and creates no new ledger entry.
2. **Ledger Consistency (ledger-001)**: A 200 means the sender lost exactly X and the recipient gained exactly X. A failure means nothing moved.
3. **No PII (pii-001)**: No response or log line contains a full account or ID number in plaintext.

## Planted Bugs (each targets one invariant)

| Bug | What goes wrong | Invariant that catches it |
|-----|-----------------|---------------------------|
| `double_charge` | Retry with same idempotency key charges again | idem-001 |
| `phantom_success` | 200 OK + ledger row, but recipient never credited | ledger-001 |
| `pii_leak` | Error messages echo full synthetic account numbers | pii-001 |

## Layout

```
bank/app.py      fake bank with switchable planted bugs
agent/
  planner.py     Gemini: OpenAPI spec → invariants + test cases (JSON)
  runner.py      plain Python: fires cases, checks the ledger
  report.py      hit-rate table: bugs planted vs caught, false alarms
results/         hit-rate table: bugs planted vs caught, false alarms
try.py           manual proof of the double-charge bug
```

## Quickstart

```bash
# 1. Set up environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Copy .env.example to .env and add your Gemini API key
cp .env.example .env
# edit .env with your GEMINI_API_KEY

# 3. Generate OpenAPI spec from the bank
python -c "import bank.app; import json; print(json.dumps(bank.app.app.openapi(), indent=2))" > bank/openapi.json

# 4. Generate test plan (optional - pre-generated plan exists)
python agent/planner.py

# 5. Start the bank (correct behavior)
uvicorn bank.app:app --host 127.0.0.1 --port 8000

# 6. Run the test suite
python agent/runner.py

# 7. Generate report
python agent/report.py
cat results/hit_rate.md
```

## Testing the Bugs

```bash
# Stop bank (Ctrl+C), then restart with bugs enabled
BUGS=double_charge,phantom_success,pii_leak uvicorn bank.app:app --host 127.0.0.1 --port 8000

# In another terminal, run tests again
python agent/runner.py
python agent/report.py
cat results/hit_rate.md
```

### Expected Results

| Bug State | Tests | Bugs Caught | Verdict |
|-----------|-------|-------------|---------|
| **OFF** (correct) | 11/11 PASS | 0/0 | ⏸️ SKIPPED |
| **ON** (all 3 bugs) | 10 FAIL, 1 PASS | 3/3 | 🟢 EXCELLENT |

### Test Cases (11 total)

| ID | Name | Invariants Checked | Catches |
|----|------|-------------------|---------|
| tc-001 | Happy path transfer | ledger-001, pii-001 | phantom_success |
| tc-002 | Retry with same idempotency key | idem-001, ledger-001 | double_charge, phantom_success |
| tc-003 | Boundary: exact balance drain | ledger-001, pii-001 | phantom_success |
| tc-004 | Boundary: balance + 1 (insufficient funds) | ledger-001, pii-001 | pii_leak |
| tc-005 | Self-transfer (A to A) | ledger-001, pii-001 | phantom_success |
| tc-006 | Missing idempotency key | ledger-001, pii-001 | — |
| tc-007 | Huge integer amount | ledger-001, pii-001 | pii_leak |
| tc-008 | Concurrent transfers (race condition) | idem-001, ledger-001 | double_charge, phantom_success |
| tc-009 | Zero amount | ledger-001, pii-001 | pii_leak |
| tc-010 | Negative amount | ledger-001, pii-001 | pii_leak |
| tc-011 | Unknown account | ledger-001, pii-001 | pii_leak |

## Manual Proof (try.py)

```bash
# With bug ON
BUGS=double_charge uvicorn bank.app:app --reload
python try.py
# Account A drops by R1000, ledger has 2 rows

# With bug OFF
uvicorn bank.app:app --reload
python try.py
# Account A drops by R500, ledger has 1 row
```

## Components

### Bank (`bank/app.py`)
- FastAPI server with in-memory accounts & ledger
- `/transfer` endpoint with idempotency key header
- Test-only endpoints: `/accounts/{acc}`, `/ledger`, `/_test/reset`, `/_test/config`
- Plantable bugs via `BUGS` env var: `double_charge`, `phantom_success`, `pii_leak`
- Synthetic account numbers for PII testing: A=1234567890, B=0987654321

### Planner (`agent/planner.py`)
- Loads OpenAPI spec from `bank/openapi.json`
- Uses Gemini to generate `agent/test_plan.json` with:
  - Money-moving endpoints
  - Fixed invariants (idem-001, ledger-001, pii-001)
  - Derived test cases covering boundaries, self-transfer, missing header, huge int, concurrency

### Runner (`agent/runner.py`)
- Deterministic executor — no LLM calls
- Resets bank before each test case for isolation
- Fires requests (sequential or concurrent via threads), snapshots balances & ledger before/after
- Verifies invariants by reading truth endpoints, not trusting HTTP status
- Labels each finding by the invariant that failed

### Report (`agent/report.py`)
- Reads `results/run_results.json`
- Queries `/_test/config` for ground-truth planted bugs
- Generates `results/hit_rate.md` with:
  - Bug detection matrix (planted vs caught by distinct type)
  - Per-test results
  - Detailed findings for failures
  - False alarm analysis
  - Overall verdict (EXCELLENT/GOOD/PARTIAL/POOR/SKIPPED)

## POPIA

All data is synthetic. No personal information is collected or stored. The
only planned outbound call is the API spec and test results to the LLM
provider; no real customer data is ever sent.