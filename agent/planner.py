"""
Planner: OpenAPI spec -> invariants + test cases (JSON).

The LLM's job is to THINK: read the spec, decide which endpoints move money, and
invent edge cases a human tester might not write. It does NOT judge results; the
deterministic runner does that by reading the ledger.

The prompt deliberately contains NO example test cases, so every case in
agent/test_plan.json has to come from the model's own reading of the spec.
"""
import json
import os
import time
from pathlib import Path

ALLOWED_INVARIANTS = {"idem-001", "ledger-001", "pii-001"}
MIN_CASES = 10
MAX_ATTEMPTS = 3

# What a human tester would be handed alongside the spec: the test environment.
TEST_ENVIRONMENT = """\
Test environment (synthetic data):
- Two accounts exist: "A" with 100000 cents (R1000.00) and "B" with 50000 cents (R500.00).
- Any other account id is unknown to the bank.
- Amounts are integers in cents.
- The bank is reset to this state before every test case.
"""

PROMPT = """\
You are a senior QA engineer designing tests for a payments API. Read the OpenAPI
spec and the test environment below, then return ONE JSON object.

{env}
Rules the system must always obey (reference them by id):
- idem-001: a retry with the same Idempotency-Key returns the same response and
  creates no new ledger entry.
- ledger-001: a 200 means the sender lost exactly the amount and the recipient
  gained exactly the amount; a failed request moves nothing.
- pii-001: no response contains a full account or ID number.

Your job:
1. Identify which endpoints move money.
2. Invent at least {min_cases} DISTINCT test cases against those endpoints that try to
   BREAK those rules. Think like an attacker and like a careless client. Cover, at least:
   - boundary amounts around a balance (exactly the balance, one cent over)
   - amounts that are zero, negative, or absurdly large
   - sending an account money to itself
   - unknown accounts on either side
   - retries (repeat 2 and 3) with the same Idempotency-Key
   - a missing or empty Idempotency-Key header
   - anything else the spec suggests that I did not list
3. For every case, set expected_status to your best guess of the CORRECT status code.
   It is a hint only; the runner judges by reading balances and the ledger.

Output schema (types, not values):
{{
  "money_moving_endpoints": [{{"method": str, "path": str, "description": str}}],
  "invariants": [{{"id": "idem-001"|"ledger-001"|"pii-001", "name": str, "description": str}}],
  "test_cases": [{{
    "id": "tc-NNN" (unique),
    "name": str (unique, says what is being attacked),
    "endpoint": str (a path from the spec),
    "method": "POST",
    "payload": {{"from_acc": str, "to_acc": str, "amount": int}},
    "headers": {{"Idempotency-Key": str}}  (use {{}} to omit the header),
    "repeat": int 1..5 (how many times the identical request is sent in a row),
    "expected_status": int,
    "invariants_to_check": [invariant ids]
  }}]
}}

Return only the JSON object, with no markdown and no commentary.

OpenAPI spec:
{spec}
"""


def validate_plan(plan, spec):
    """Return (errors, warnings). Errors make the plan unusable; warnings are coverage gaps."""
    errors, warnings = [], []
    if not isinstance(plan, dict):
        return ["plan is not a JSON object"], warnings
    cases = plan.get("test_cases")
    if not isinstance(cases, list) or not cases:
        return ["test_cases missing or empty"], warnings
    if not isinstance(plan.get("invariants"), list):
        errors.append("invariants missing")

    paths = set(spec.get("paths", {}))
    seen_ids, seen_names, seen_sig = set(), set(), set()
    for i, tc in enumerate(cases):
        where = f"test_cases[{i}]"
        if not isinstance(tc, dict):
            errors.append(f"{where} is not an object")
            continue
        for key in ("id", "name", "endpoint", "method", "payload", "expected_status", "invariants_to_check"):
            if key not in tc:
                errors.append(f"{where} missing '{key}'")
        if errors and any(e.startswith(where) for e in errors):
            continue
        if tc["id"] in seen_ids:
            errors.append(f"{where} duplicate id {tc['id']}")
        seen_ids.add(tc["id"])
        if tc["name"] in seen_names:
            errors.append(f"{where} duplicate name {tc['name']!r}")
        seen_names.add(tc["name"])
        if tc["endpoint"] not in paths:
            errors.append(f"{where} endpoint {tc['endpoint']!r} is not in the spec")
        elif tc["endpoint"] != "/transfer":
            errors.append(f"{where} the runner only executes POST /transfer, got {tc['endpoint']!r}")
        p = tc["payload"]
        if not (isinstance(p, dict) and isinstance(p.get("from_acc"), str)
                and isinstance(p.get("to_acc"), str) and isinstance(p.get("amount"), int)
                and not isinstance(p.get("amount"), bool)):
            errors.append(f"{where} payload must have str from_acc, str to_acc, int amount")
        h = tc.get("headers", {})
        if not (isinstance(h, dict) and all(isinstance(v, str) for v in h.values())):
            errors.append(f"{where} headers must be an object of strings")
        r = tc.get("repeat", 1)
        if not (isinstance(r, int) and 1 <= r <= 5):
            errors.append(f"{where} repeat must be an int 1..5")
        if not isinstance(tc["expected_status"], int):
            errors.append(f"{where} expected_status must be an int")
        bad = set(tc["invariants_to_check"]) - ALLOWED_INVARIANTS if isinstance(tc["invariants_to_check"], list) else {"?"}
        if bad:
            errors.append(f"{where} unknown invariants {sorted(bad)}")
        sig = json.dumps([tc["endpoint"], p, h, r], sort_keys=True, default=str)
        if sig in seen_sig:
            errors.append(f"{where} is an exact duplicate of another case")
        seen_sig.add(sig)

    if errors:
        return errors, warnings

    if len(cases) < MIN_CASES:
        warnings.append(f"only {len(cases)} cases (asked for at least {MIN_CASES})")
    amounts = [c["payload"]["amount"] for c in cases]
    if not any(c.get("repeat", 1) >= 2 for c in cases):
        warnings.append("no retry case")
    if not any(a <= 0 for a in amounts):
        warnings.append("no zero/negative amount case")
    if not any(c["payload"]["from_acc"] == c["payload"]["to_acc"] for c in cases):
        warnings.append("no self-transfer case")
    if not any(a > 100_000 for a in amounts):
        warnings.append("no over-balance/huge amount case")
    if not any(not c.get("headers") for c in cases):
        warnings.append("no missing-Idempotency-Key case")
    return errors, warnings


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def generate_test_plan(spec: dict) -> dict:
    import google.generativeai as genai  # imported lazily so validate_plan is testable offline
    from dotenv import load_dotenv

    load_dotenv()
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set (copy .env.example to .env)")
    genai.configure(api_key=key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    model = genai.GenerativeModel(
        model_name,
        generation_config=genai.GenerationConfig(
            temperature=0.8, response_mime_type="application/json"
        ),
    )

    prompt = PROMPT.format(env=TEST_ENVIRONMENT, min_cases=MIN_CASES, spec=json.dumps(spec, indent=2))
    feedback = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"Asking {model_name} (attempt {attempt}/{MAX_ATTEMPTS})...")
        text = _strip_fences(model.generate_content(prompt + feedback).text)
        try:
            plan = json.loads(text)
        except json.JSONDecodeError as e:
            feedback = f"\n\nYour previous reply was not valid JSON ({e}). Return only the JSON object."
            continue
        errors, warnings = validate_plan(plan, spec)
        if not errors:
            for w in warnings:
                print(f"  warning: {w}")
            plan["generated_by"] = {"model": model_name, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            return plan
        print("  plan rejected:", "; ".join(errors[:5]))
        feedback = "\n\nYour previous plan was rejected for these problems, fix them:\n- " + "\n- ".join(errors[:10])
    raise RuntimeError("could not get a valid plan from the model")


def main():
    spec_path = Path("bank/openapi.json")
    if not spec_path.exists():
        print("No bank/openapi.json. Generate it first:")
        print('  python -c "import bank.app, json; print(json.dumps(bank.app.app.openapi(), indent=2))" > bank/openapi.json')
        return
    spec = json.loads(spec_path.read_text())
    plan = generate_test_plan(spec)
    Path("agent/test_plan.json").write_text(json.dumps(plan, indent=2))
    print(f"Wrote agent/test_plan.json with {len(plan['test_cases'])} test cases")
    for tc in plan["test_cases"]:
        print(f"  {tc['id']}: {tc['name']}")


if __name__ == "__main__":
    main()