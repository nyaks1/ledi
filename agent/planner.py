"""
Planner: OpenAPI spec → invariants + test cases (JSON)
Uses Gemini to analyze the API and generate test cases for money-moving endpoints.
"""
import json
import os
from pathlib import Path
from typing import Any

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY not set in environment")

genai.configure(api_key=GEMINI_API_KEY)
MODEL = genai.GenerativeModel("gemini-flash-latest")


def load_openapi_spec(spec_path: str | Path) -> dict[str, Any]:
    """Load OpenAPI spec from JSON file."""
    with open(spec_path) as f:
        return json.load(f)


def generate_test_plan(openapi_spec: dict[str, Any]) -> dict[str, Any]:
    """
    Send OpenAPI spec to Gemini and get back:
    - money_moving_endpoints: list of endpoints that transfer value
    - invariants: rules that must always hold
    - test_cases: concrete test scenarios to execute
    """
    prompt = f"""
You are a security-focused API test planner for a payment system.
Analyze this OpenAPI spec and identify:

1. MONEY-MOVING ENDPOINTS: Which endpoints actually transfer value between accounts?
2. INVARIANTS: Rules that must ALWAYS hold for correctness (see examples below).
3. TEST CASES: Concrete scenarios to fire against the API to find bugs.

Return ONLY valid JSON with this exact structure:
{{
  "money_moving_endpoints": [
    {{"method": "POST", "path": "/transfer", "description": "Transfers cents between accounts"}}
  ],
  "invariants": [
    {{
      "id": "idem-001",
      "name": "Idempotency",
      "description": "Same idempotency key returns same response, creates no new ledger entry",
      "check": "ledger_count_before == ledger_count_after && response_before == response_after"
    }},
    {{
      "id": "ledger-001",
      "name": "Ledger Consistency",
      "description": "200 OK means sender lost exactly X and recipient gained exactly X; failure means nothing moved",
      "check": "balance_sender_before - balance_sender_after == amount && balance_recipient_after - balance_recipient_before == amount"
    }},
    {{
      "id": "pii-001",
      "name": "No PII in Responses",
      "description": "No response or log line contains full account or ID number in plaintext",
      "check": "no full account numbers in any response body or log"
    }}
  ],
  "test_cases": [
    {{
      "id": "tc-001",
      "name": "Happy path transfer",
      "endpoint": "/transfer",
      "method": "POST",
      "payload": {{"from_acc": "A", "to_acc": "B", "amount": 50000}},
      "headers": {{"Idempotency-Key": "idem-happy-001"}},
      "expected_status": 200,
      "invariants_to_check": ["ledger-001", "pii-001"]
    }},
    {{
      "id": "tc-002",
      "name": "Retry with same idempotency key",
      "endpoint": "/transfer",
      "method": "POST",
      "payload": {{"from_acc": "A", "to_acc": "B", "amount": 50000}},
      "headers": {{"Idempotency-Key": "idem-retry-001"}},
      "repeat": 2,
      "expected_status": 200,
      "invariants_to_check": ["idem-001", "ledger-001"]
    }},
    {{
      "id": "tc-003",
      "name": "Insufficient funds",
      "endpoint": "/transfer",
      "method": "POST",
      "payload": {{"from_acc": "B", "to_acc": "A", "amount": 60000}},
      "headers": {{"Idempotency-Key": "idem-insufficient-001"}},
      "expected_status": 400,
      "invariants_to_check": ["ledger-001"]
    }},
    {{
      "id": "tc-004",
      "name": "Unknown account",
      "endpoint": "/transfer",
      "method": "POST",
      "payload": {{"from_acc": "Z", "to_acc": "B", "amount": 1000}},
      "headers": {{"Idempotency-Key": "idem-unknown-001"}},
      "expected_status": 404,
      "invariants_to_check": ["ledger-001"]
    }},
    {{
      "id": "tc-005",
      "name": "Zero amount",
      "endpoint": "/transfer",
      "method": "POST",
      "payload": {{"from_acc": "A", "to_acc": "B", "amount": 0}},
      "headers": {{"Idempotency-Key": "idem-zero-001"}},
      "expected_status": 400,
      "invariants_to_check": ["ledger-001"]
    }},
    {{
      "id": "tc-006",
      "name": "Negative amount",
      "endpoint": "/transfer",
      "method": "POST",
      "payload": {{"from_acc": "A", "to_acc": "B", "amount": -100}},
      "headers": {{"Idempotency-Key": "idem-negative-001"}},
      "expected_status": 400,
      "invariants_to_check": ["ledger-001"]
    }},
    {{
      "id": "tc-007",
      "name": "Concurrent transfers same account",
      "endpoint": "/transfer",
      "method": "POST",
      "payload": {{"from_acc": "A", "to_acc": "B", "amount": 30000}},
      "headers": {{"Idempotency-Key": "idem-concurrent-001"}},
      "repeat": 3,
      "expected_status": 200,
      "invariants_to_check": ["idem-001", "ledger-001"]
    }}
  ]
}}

OpenAPI Spec:
{json.dumps(openapi_spec, indent=2)}

RULES:
- Only return the JSON object, no markdown, no explanation
- The test_cases should cover: happy path, idempotency retry, error cases, edge cases
- Each test_case must reference invariants_to_check by ID
- For idempotency tests, use "repeat": 2 (or more) to indicate retry
- Amounts are in cents (integers)
"""

    response = MODEL.generate_content(prompt)
    text = response.text.strip()

    # Strip markdown code fences if present
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]

    # Debug: print raw response
    print("=== RAW RESPONSE ===")
    print(text[:500])
    print("====================")

    return json.loads(text.strip())


def main():
    # Try to find the OpenAPI spec - first check if there's a saved one,
    # otherwise we'll need to generate it from the running app
    spec_path = Path("bank/openapi.json")

    if spec_path.exists():
        print(f"Loading OpenAPI spec from {spec_path}")
        spec = load_openapi_spec(spec_path)
    else:
        print("No openapi.json found. Generate it first with:")
        print("  python -c \"import bank.app; import json; print(json.dumps(bank.app.app.openapi(), indent=2))\" > bank/openapi.json")
        return

    print("Generating test plan with Gemini...")
    plan = generate_test_plan(spec)

    output_path = Path("agent/test_plan.json")
    output_path.write_text(json.dumps(plan, indent=2))
    print(f"Test plan written to {output_path}")
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()