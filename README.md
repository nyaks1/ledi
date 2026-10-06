# sebaka-agent

An AI agent for Software Quality Engineering (API testing, money-moving APIs).

> Status: work in progress for the Sebaka AI Agent Challenge. The fake bank
> below is built; the test agent is next.

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
agent/           planner (LLM), runner (deterministic), report  [next]
results/         hit-rate table: bugs planted vs caught, false alarms
try.py           manual proof of the double-charge bug
```

## Run the fake bank

```
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

set BUGS=double_charge        # Windows (bug ON)
uvicorn bank.app:app --reload
```

On Linux/macOS use `BUGS=double_charge uvicorn bank.app:app --reload`.
Leave `BUGS` unset for the correct behaviour.

Then `python try.py`: with the bug on, account A drops by R1000 and the ledger
has 2 rows. With it off, A drops by R500 and the ledger has 1 row.

## POPIA

All data is synthetic. No personal information is collected or stored. The
only planned outbound call is the API spec and test results to the LLM
provider; no real customer data is ever sent.