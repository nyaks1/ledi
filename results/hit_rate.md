# QE Evaluation Report

- **Active Planted Invariants:** double_charge, pii_leak, latency_spike, phantom_success
- **Detected Invariants:** double_charge, pii_leak, latency_spike, phantom_success
- **Hit Rate:** 100.0% (4/4)
- **False Alarms:** 0

## Test Suite Execution Log:
- **[VIOLATION]** Functional - Idempotency (tc-func-01): VIOLATION [double_charge]: Retried transfer created duplicate ledger records.
- **[VIOLATION]** Functional - Conservation (tc-func-02): VIOLATION [phantom_success]: Balance destroyed; funds debited without crediting recipient.
- **[PASSED]** Functional - Unknown Account (tc-func-03): Passed: Unknown account rejected safely.
- **[VIOLATION]** Performance - Latency SLA (tc-perf-01): VIOLATION [latency_spike]: SLA breached. Response took 1218.4ms (threshold: 400ms).
- **[VIOLATION]** Security - Error Leakage (tc-sec-01): VIOLATION [pii_leak]: Response disclosed internal system infrastructure: {"detail":"DB error: account NONEXISTENT not found in postgres-cluster-za-central"}
