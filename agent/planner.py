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
    - invariants: rules that must always hold (fixed set)
    - test_cases: concrete test scenarios derived from the spec
    """
    prompt = f"""
You are a security-focused API test planner for a payment system.
Analyze this OpenAPI spec and derive test cases that target the three invariants below.

Return ONLY valid JSON with this exact structure (no markdown, no explanation):
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
    // Derive cases from the spec. Required coverage:
    // 1. Happy path (valid transfer, checks ledger-001, pii-001)
    // 2. Idempotency retry (same key, repeat=2, checks idem-001, ledger-001)
    // 3. Boundary: amount == sender balance (exact drain)
    // 4. Boundary: amount == sender balance + 1 (insufficient funds)
    // 5. Self-transfer (from_acc == to_acc)
    // 6. Missing idempotency key header
    // 7. Huge integer amount (overflow/edge)
    // 8. Concurrent requests (concurrent=true, repeat=3, checks idem-001, ledger-001)
    // 9. Invalid amount: zero, negative
    // 10. Unknown account
    // Each case needs: id, name, endpoint, method, payload, headers, expected_status, invariants_to_check
    // Use "concurrent": true for parallel execution, "repeat" for sequential retries
  ]
}}

OpenAPI Spec:
{json.dumps(openapi_spec, indent=2)}

RULES:
- Only return the JSON object, no markdown, no explanation
- Amounts are in cents (integers)
- Accounts in spec: A (100000 cents), B (50000 cents)
- Idempotency-Key header is required per spec
- For concurrent tests, use "concurrent": true and "repeat": N
- For sequential retries, use "repeat": N without "concurrent"
- Each test_case MUST reference invariants_to_check by ID from the three invariants above
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