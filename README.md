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

1. A retried request (same idempotency key) returns the same response and
   creates no new ledger entry.
2. A 200 means the sender lost exactly X and the recipient gained exactly X.
   A failure means nothing moved.
3. No response or log line contains a full account or ID number in plaintext.

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

## Testing the Bug

```bash
# Stop bank (Ctrl+C), then restart with bug enabled
BUGS=double_charge uvicorn bank.app:app --host 127.0.0.1 --port 8000

# In another terminal, run tests again
python agent/runner.py
python agent/report.py
cat results/hit_rate.md
```

### Expected Results

| Bug State | tc-002 (Retry) | tc-007 (Concurrent) | Verdict |
|-----------|----------------|---------------------|---------|
| **OFF** (correct) | ✅ PASS | ✅ PASS | ⏸️ SKIPPED (no bugs planted) |
| **ON** (double_charge) | ❌ FAIL 🐛 | ❌ FAIL 🐛 | 🟢 EXCELLENT (bug caught) |

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
- Test-only endpoints: `/accounts/{acc}`, `/ledger`, `/_test/reset`
- Plantable bugs via `BUGS` env var (currently: `double_charge`)

### Planner (`agent/planner.py`)
- Loads OpenAPI spec from `bank/openapi.json`
- Uses Gemini to generate `agent/test_plan.json` with:
  - Money-moving endpoints
  - Invariants (idempotency, ledger consistency, no PII)
  - Test cases (happy path, retry, error cases, edge cases)

### Runner (`agent/runner.py`)
- Deterministic executor — no LLM calls
- Resets bank before each test case for isolation
- Fires requests, snapshots balances & ledger before/after
- Verifies invariants by reading truth endpoints, not trusting HTTP status

### Report (`agent/report.py`)
- Reads `results/run_results.json`
- Generates `results/hit_rate.md` with:
  - Bug detection matrix (planted vs caught)
  - Per-test results
  - Detailed findings for failures
  - False alarm analysis
  - Overall verdict

## POPIA

All data is synthetic. No personal information is collected or stored. The
only planned outbound call is the API spec and test results to the LLM
provider; no real customer data is ever sent.