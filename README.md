# sebaka-agent

An AI agent that tests money-moving APIs. It reads an OpenAPI spec, invents
attacks a human tester might not write, fires them, and judges the result by
**reading the ledger and balances, never by trusting "200 OK"**.

Built for the Sebaka AI Agent Challenge (Software Quality Engineering, API testing).

## Problem

A test suite is a list of what a human imagined. The payment bug that reaches
production is the one nobody imagined: a phone drops signal, the backend charges,
the client retries, and the customer is charged twice.

## Villain

The untested gap between what a payment API promises and what it actually does.

## The agent: receives, decides, does, returns

| Step | Who does it | What happens |
|---|---|---|
| Receives | `agent/planner.py` | the OpenAPI spec and a description of the test accounts |
| Decides | Gemini (LLM) | which endpoints move money, and which edge cases try to break three rules |
| Does | `agent/runner.py` (plain Python, no LLM) | fires every case, then reads `/ledger` and `/accounts/{id}` |
| Returns | `agent/report.py` | only violations it reproduced, with the rule that broke |

The LLM invents the attacks. Deterministic code judges them, so the verdict is
never a model's opinion.

## The three rules

1. **idem-001**: a retry with the same Idempotency-Key returns the same response
   and creates no new ledger entry.
2. **ledger-001**: a 200 means the sender lost exactly X and the recipient gained
   exactly X; a failed request moves nothing.
3. **pii-001**: no response contains a full account or ID number.

## Proof it works (and doesn't cry wolf)

`agent/evaluate.py` runs the same test plan against five versions of a fake bank:
clean, each planted bug alone, and all three together. Results are in
[`results/hit_rate.md`](results/hit_rate.md).

| Planted bug | Rule that catches it |
|---|---|
| `double_charge` (retry charges again) | idem-001 |
| `phantom_success` (sender charged, recipient never credited, 200 returned) | ledger-001 |
| `pii_leak` (error message echoes a full account number) | pii-001 |

The key number is the **clean bank row: zero false findings**. An agent that
flags problems that aren't there gets ignored by the team within a week.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add your GEMINI_API_KEY

# 1. export the spec the planner reads
python -c "import bank.app, json; print(json.dumps(bank.app.app.openapi(), indent=2))" > bank/openapi.json

# 2. the LLM writes the test plan (agent/test_plan.json is committed as a fallback)
python agent/planner.py

# 3. run the plan against all five bank configurations and write the report
python agent/evaluate.py
cat results/hit_rate.md
```

`evaluate.py` starts and stops the fake bank itself and needs no network, so
step 3 works offline. Only step 2 calls Gemini.

To try one configuration by hand:

```bash
BUGS=double_charge uvicorn bank.app:app --port 8000     # terminal 1
python agent/runner.py                                  # terminal 2
```

## Layout

```
bank/app.py          fake bank with switchable planted bugs (BUGS env var)
bank/openapi.json    the spec the planner reads
agent/planner.py     spec -> rules + test cases (Gemini), with schema validation and retries
agent/runner.py      deterministic executor and judge
agent/evaluate.py    five bank configurations -> results/evaluation.json + hit_rate.md
agent/report.py      renders the hit-rate report
agent/test_plan.json the generated plan
results/             evaluation output
```

## Limits

- The three bug classes and the three rules were designed together, so a high
  catch rate shows the pipeline works, not that it finds unknown bugs.
- The runner sends retries one after another. It does **not** test true
  concurrency or race conditions.
- The runner only executes `POST /transfer`.
- The bank is a small in-memory fake with test-only endpoints (`/ledger`,
  `/accounts/{id}`). A real system would need an equivalent read-only audit view.
- Cases where the planner's expected status differs from the bank's are listed
  in the report for a human to triage. They are not counted as bugs.

## POPIA

All data is synthetic (two fake accounts, fake account numbers). No personal
information is collected or stored. The only outbound call is to Gemini, and it
receives the OpenAPI spec and a description of the synthetic test accounts. It
never receives test results or responses. Nothing is retained by this project;
the bank resets between cases.