---
status: testing
phase: 03-capacity-aware-coordinated-planning
source: [03-VERIFICATION.md]
started: 2026-10-20T23:00:00Z
updated: 2026-10-20T23:00:00Z
---

## Current Test

number: 1
name: Run the planner on the real Bandipur graph with the real-location seed and an operator-chosen fire, and judge the plan (live stack)
expected: |
  A pending_review plan (or a failed plan whose reasons make operational sense) with routes that follow
  real roads to real schools; capacities flagged as estimates
awaiting: user response

## Tests

### 1. Real-graph planner run (live stack)
expected: A pending_review plan (or a failed plan whose reasons make operational sense) with routes that follow real roads to real schools; capacities flagged as estimates
result: [pending]

### 2. V3 start-node policy decision (WR-07 / D-07 / D-21)
expected: Either confirmed as fail-closed policy, or a rule for "depart through the P50 zone when it is the only way out, flagged high risk" (optionally naming the origin-edge cause in the failure reason)
result: [pending]

### 3. Sourced shelter capacities and settlement populations (D-18)
expected: Rows carry a real capacity_source/pop_source and is_simulated=false; the S9 estimate warning disappears from plans
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
