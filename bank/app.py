import os
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Fake Bank (planted bugs)")

# Bugs switch on via env var, e.g.  set BUGS=double_charge,phantom_success,pii_leak
BUGS = set(filter(None, os.getenv("BUGS", "").split(",")))

accounts = {"A": 100_000, "B": 50_000}  # R1000.00 and R500.00
ledger = []        # one row per executed transfer
seen_keys = {}     # idempotency key -> saved response

class Transfer(BaseModel):
    from_acc: str
    to_acc: str
    amount: int  # cents

@app.post("/transfer")
def transfer(t: Transfer, idempotency_key: str = Header(...)):
    # Correct behaviour: same key = same answer, no second charge
    if "double_charge" not in BUGS and idempotency_key in seen_keys:
        return seen_keys[idempotency_key]

    if t.from_acc not in accounts or t.to_acc not in accounts:
        # pii_leak: echo full account number in error
        if "pii_leak" in BUGS:
            raise HTTPException(404, f"unknown account {t.from_acc} -> {t.to_acc}")
        raise HTTPException(404, "unknown account")

    if t.amount <= 0 or accounts[t.from_acc] < t.amount:
        # pii_leak: echo full account number in error
        if "pii_leak" in BUGS:
            raise HTTPException(400, f"invalid amount {t.amount} for account {t.from_acc} (balance {accounts[t.from_acc]})")
        raise HTTPException(400, "invalid amount")

    accounts[t.from_acc] -= t.amount
    accounts[t.to_acc] += t.amount
    ledger.append({"from": t.from_acc, "to": t.to_acc, "amount": t.amount})

    resp = {"status": "ok", "ledger_id": len(ledger)}

    # phantom_success: return 200 and ledger row, but don't credit recipient
    if "phantom_success" in BUGS:
        accounts[t.to_acc] -= t.amount  # roll back recipient credit
        resp["phantom"] = True  # marker for test visibility

    seen_keys[idempotency_key] = resp
    return resp

# Test-only endpoints: the agent reads these instead of trusting "200 OK"
@app.get("/accounts/{acc}")
def balance(acc: str):
    return {"balance": accounts[acc]}

@app.get("/ledger")
def get_ledger():
    return ledger

# Test-only: reset to initial state
@app.post("/_test/reset")
def reset():
    global accounts, ledger, seen_keys
    accounts = {"A": 100_000, "B": 50_000}
    ledger = []
    seen_keys = {}
    return {"status": "reset"}

# Test-only: report which bugs are active
@app.get("/_test/config")
def config():
    return {"active_bugs": sorted(BUGS)}