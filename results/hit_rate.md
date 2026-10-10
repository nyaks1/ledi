# Hit Rate Report

Generated 2026-10-10 07:37:27 from **12 test cases** run against **5 bank configurations**.

## Headline

- **Planted bugs caught: 6/6** (each bug counted once per scenario where it is planted)
- **False findings (flagged but not planted): 0**
- **Clean bank: 12 cases, 0 false findings**

## Per scenario

| Scenario | Planted | Caught | Missed | False findings | Cases failed |
|---|---|---|---|---|---|
| clean (no bugs) | — | — | — | — | 0/12 |
| double_charge | double_charge | double_charge | — | — | 2/12 |
| phantom_success | phantom_success | phantom_success | — | — | 4/12 |
| pii_leak | pii_leak | pii_leak | — | — | 4/12 |
| double_charge+phantom_success+pii_leak | double_charge, phantom_success, pii_leak | double_charge, phantom_success, pii_leak | — | — | 8/12 |

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

### pii_leak
- **tc-002** Transfer one cent more than sender available balance
  - [pii-001] VIOLATION: response 1 contains a 10-digit number (…90)
- **tc-003** Transfer zero amount
  - [pii-001] VIOLATION: response 1 contains a 10-digit number (…90)
- **tc-004** Transfer negative amount to siphon money
  - [pii-001] VIOLATION: response 1 contains a 10-digit number (…90)
- **tc-005** Transfer absurdly large amount exceeding maximum plausible balance
  - [pii-001] VIOLATION: response 1 contains a 10-digit number (…90)

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

- The three bug classes and the three rules were designed together by the author, so a high catch rate shows the pipeline works, not that it generalises to unknown bugs.
- The bank is a small in-memory fake with test-only endpoints (`/ledger`, `/accounts/{id}`). A real bank would need an equivalent read-only audit view.
- All data is synthetic. No personal information is stored or sent anywhere.
