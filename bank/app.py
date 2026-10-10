import os
import threading
import time

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Fake Bank (planted bugs)")

# Bugs switch on via env var, e.g.  BUGS=double_charge,phantom_success,pii_leak,slow_response
BUGS = set(filter(None, os.getenv("BUGS", "").split(",")))

# Money is stored in cents, because floats lose cents.
INITIAL_ACCOUNTS = {"A": 100_000, "B": 50_000}  # R1000.00 and R500.00
ACCOUNT_NUMBERS = {"A": "1234567890", "B": "0987654321"}  # fake, synthetic

accounts = dict(INITIAL_ACCOUNTS)
ledger = []      # one row per executed transfer
seen_keys = {}   # idempotency key -> saved response
lock = threading.Lock()  # one transfer mutates state at a time (correct under load)

SLOW_SECONDS = 0.8  # planted slow_response bug


class Transfer(BaseModel):
    from_acc: str
    to_acc: str
    amount: int  # cents


@app.post("/transfer")
def transfer(t: Transfer, idempotency_key: str = Header(...)):
    if "slow_response" in BUGS:
        # Planted bug: every transfer is slow (outside the lock, so requests overlap).
        time.sleep(SLOW_SECONDS)
    with lock:
        return _do_transfer(t, idempotency_key)


def _do_transfer(t: Transfer, idempotency_key: str):
    # Correct behaviour: same key = same answer, no second charge.
    if "double_charge" not in BUGS and idempotency_key in seen_keys:
        return seen_keys[idempotency_key]

    if t.from_acc not in accounts or t.to_acc not in accounts:
        raise HTTPException(404, "unknown account")
    if t.from_acc == t.to_acc:
        raise HTTPException(400, "cannot transfer to the same account")
    if t.amount <= 0 or accounts[t.from_acc] < t.amount:
        detail = "invalid amount"
        if "pii_leak" in BUGS:
            # Planted bug: error message echoes a full account number.
            detail += f" for account {ACCOUNT_NUMBERS[t.from_acc]}"
        raise HTTPException(400, detail)

    accounts[t.from_acc] -= t.amount
    if "phantom_success" not in BUGS:
        # Planted bug when on: sender is charged, recipient is never credited.
        accounts[t.to_acc] += t.amount
    ledger.append({"from": t.from_acc, "to": t.to_acc, "amount": t.amount})

    resp = {"status": "ok", "ledger_id": len(ledger)}
    seen_keys[idempotency_key] = resp
    return resp


# Test-only endpoints: the agent reads these instead of trusting "200 OK".
@app.get("/accounts/{acc}")
def balance(acc: str):
    if acc not in accounts:
        raise HTTPException(404, "unknown account")
    return {"balance": accounts[acc]}


@app.get("/ledger")
def get_ledger():
    return ledger


# Test-only: which bugs are planted (used by the evaluation report only).
@app.get("/_test/config")
def config():
    return {"active_bugs": sorted(BUGS)}


# Test-only: reset to initial state (mutate in place, no globals juggling).
@app.post("/_test/reset")
def reset():
    accounts.clear()
    accounts.update(INITIAL_ACCOUNTS)
    ledger.clear()
    seen_keys.clear()
    return {"status": "reset"}
