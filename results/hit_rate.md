# Hit Rate Report

Generated 2026-10-10 12:58:31 from **12 planner-written test cases plus 1 built-in load check** run against **6 bank configurations**.

## Headline

- **Planted bugs caught: 8/8** (each bug counted once per scenario where it is planted)
- **False findings (flagged but not planted): 0**
- **Clean bank: 13 cases, 0 false findings**

## Per scenario

| Scenario | Planted | Caught | Missed | False findings | Cases failed |
|---|---|---|---|---|---|
| clean (no bugs) | — | — | — | — | 0/13 |
| double_charge | double_charge | double_charge | — | — | 2/13 |
| phantom_success | phantom_success | phantom_success | — | — | 5/13 |
| pii_leak | pii_leak | pii_leak | — | — | 4/13 |
| slow_response | slow_response | slow_response | — | — | 12/13 |
| double_charge+phantom_success+pii_leak+slow_response | double_charge, phantom_success, pii_leak, slow_response | double_charge, phantom_success, pii_leak, slow_response | — | — | 12/13 |

## Evidence: how each bug was caught

### double_charge
- **tc-009** Replay valid transfer twice with identical idempotency key
  - [idem-001] VIOLATION: a retry with the same key created a new ledger entry
- **tc-010** Replay valid transfer three times with identical idempotency key
  - [idem-001] VIOLATION: a retry with the same key created a new ledger entry

### phantom_success
- **tc-001** Transfer exact full balance of sender account
  - [ledger-001] VIOLATION: sender and recipient amounts differ (money created or lost)
- **tc-009** Replay valid transfer twice with identical idempotency key
  - [ledger-001] VIOLATION: sender and recipient amounts differ (money created or lost)
- **tc-010** Replay valid transfer three times with identical idempotency key
  - [ledger-001] VIOLATION: sender and recipient amounts differ (money created or lost)
- **tc-012** Transfer request with empty string Idempotency-Key header
  - [ledger-001] VIOLATION: sender and recipient amounts differ (money created or lost)
- **load-001** Burst of 20 parallel transfers
  - [perf-002] VIOLATION: sender and recipient amounts differ under load (money created or lost)

### pii_leak
- **tc-002** Transfer one cent more than sender available balance
  - [pii-001] VIOLATION: response 1 contains a 10-digit number (…90)
- **tc-003** Transfer zero amount
  - [pii-001] VIOLATION: response 1 contains a 10-digit number (…90)
- **tc-004** Transfer negative amount to siphon money
  - [pii-001] VIOLATION: response 1 contains a 10-digit number (…90)
- **tc-005** Transfer absurdly large amount exceeding maximum plausible balance
  - [pii-001] VIOLATION: response 1 contains a 10-digit number (…90)

### slow_response
- **tc-001** Transfer exact full balance of sender account
  - [perf-001] VIOLATION: a response took 811 ms, over the 500 ms budget
- **tc-002** Transfer one cent more than sender available balance
  - [perf-001] VIOLATION: a response took 813 ms, over the 500 ms budget
- **tc-003** Transfer zero amount
  - [perf-001] VIOLATION: a response took 811 ms, over the 500 ms budget
- **tc-004** Transfer negative amount to siphon money
  - [perf-001] VIOLATION: a response took 804 ms, over the 500 ms budget
- **tc-005** Transfer absurdly large amount exceeding maximum plausible balance
  - [perf-001] VIOLATION: a response took 805 ms, over the 500 ms budget
- **tc-006** Transfer funds from account to itself
  - [perf-001] VIOLATION: a response took 811 ms, over the 500 ms budget
- **tc-007** Transfer from unknown sender account
  - [perf-001] VIOLATION: a response took 804 ms, over the 500 ms budget
- **tc-008** Transfer to unknown recipient account
  - [perf-001] VIOLATION: a response took 809 ms, over the 500 ms budget
- **tc-009** Replay valid transfer twice with identical idempotency key
  - [perf-001] VIOLATION: a response took 810 ms, over the 500 ms budget
- **tc-010** Replay valid transfer three times with identical idempotency key
  - [perf-001] VIOLATION: a response took 808 ms, over the 500 ms budget
- **tc-012** Transfer request with empty string Idempotency-Key header
  - [perf-001] VIOLATION: a response took 804 ms, over the 500 ms budget
- **load-001** Burst of 20 parallel transfers
  - [perf-002] VIOLATION: p95 latency 876 ms is over the 500 ms budget under load

## Needs human triage (expectation mismatches)

On the **clean** bank the planner's expected status differed from the bank's actual status. Either the planner guessed wrong or the bank has a real validation gap. Each one needs a human decision:

- tc-002 Transfer one cent more than sender available balance: request 1: expected 422, got 400
- tc-003 Transfer zero amount: request 1: expected 422, got 400
- tc-004 Transfer negative amount to siphon money: request 1: expected 422, got 400
- tc-005 Transfer absurdly large amount exceeding maximum plausible balance: request 1: expected 422, got 400
- tc-006 Transfer funds from account to itself: request 1: expected 422, got 400
- tc-007 Transfer from unknown sender account: request 1: expected 422, got 404
- tc-008 Transfer to unknown recipient account: request 1: expected 422, got 404
- tc-012 Transfer request with empty string Idempotency-Key header: request 1: expected 422, got 200

## Limits (read before trusting the numbers)

- The four bug classes and the rules were designed together by the author, so a high catch rate shows the pipeline works, not that it generalises to unknown bugs.
- Performance coverage is basic: a per-request latency budget and one burst of parallel transfers on a local fake bank. It is not a substitute for real load testing against production-like infrastructure.
- The bank is a small in-memory fake with test-only endpoints (`/ledger`, `/accounts/{id}`). A real bank would need an equivalent read-only audit view.
- All data is synthetic. No personal information is stored or sent anywhere.
