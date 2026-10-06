import requests
url = "http://127.0.0.1:8000"
body = {"from_acc": "A", "to_acc": "B", "amount": 50_000}
h = {"Idempotency-Key": "abc-123"}

requests.post(f"{url}/transfer", json=body, headers=h)
requests.post(f"{url}/transfer", json=body, headers=h)  # the "retry"

print(requests.get(f"{url}/accounts/A").json())
print(len(requests.get(f"{url}/ledger").json()), "ledger rows")