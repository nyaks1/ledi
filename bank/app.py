import os
import time
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Fake Bank (Planted Bugs)")

# Env var controls active bugs: e.g. BUGS=double_charge,latency_spike,pii_leak,phantom_success
BUGS = set(filter(None, os.getenv("BUGS", "").split(",")))
accounts = {"A": 100_000, "B": 50_000}  # R1000.00 and R500.00
ledger = []
seen_keys = {}

class Transfer(BaseModel):
    from_acc: str
    to_acc: str
    amount: int  # in cents

@app.get("/_test/config")
def get_config():
    """Ground truth endpoint for evaluation reporting."""
    return {"active_bugs": sorted(list(BUGS))}

@app.post("/transfer")
def transfer(t: Transfer, idempotency_key: str = Header(...)):
    # --- Pillar 2: Performance Bug ---
    if "latency_spike" in BUGS:
        time.sleep(1.2)  # Artificial latency breaching standard 400ms SLA

    # --- Pillar 1: Functional Bug (Idempotency) ---
    if "double_charge" not in BUGS and idempotency_key in seen_keys:
        return seen_keys[idempotency_key]

    # --- Pillar 3: Security Bug (PII / Verbose Error Leakage) ---
    if t.from_acc not in accounts or t.to_acc not in accounts:
        if "pii_leak" in BUGS:
            raise HTTPException(404, f"DB error: account {t.from_acc} not found in postgres-cluster-za-central")
        raise HTTPException(404, "unknown account")

    if t.amount <= 0 or accounts[t.from_acc] < t.amount:
        raise HTTPException(400, "invalid amount")

    # Debit sender
    accounts[t.from_acc] -= t.amount

    # --- Pillar 1: Functional Bug (Balance Conservation) ---
    if "phantom_success" not in BUGS:
        accounts[t.to_acc] += t.amount

    ledger.append({"from": t.from_acc, "to": t.to_acc, "amount": t.amount})
    resp = {"status": "ok", "ledger_id": len(ledger)}
    seen_keys[idempotency_key] = resp
    return resp

@app.get("/accounts/{acc}")
def balance(acc: str):
    if acc not in accounts:
        raise HTTPException(404, "unknown account")
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