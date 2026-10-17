---
status: testing
phase: 02-mvp-detection-to-route
source: [02-VERIFICATION.md]
started: 2026-10-17T07:30:00Z
updated: 2026-10-17T07:30:00Z
---

## Current Test

number: 1
name: Domain review of AOI-boundary exits and route suitability for Bandipur
expected: |
  An operator familiar with the Bandipur corridor agrees that using the safe road nodes nearest
  each AOI boundary as route exits is acceptable for the MVP, and that a "blocked" classification
  on the 3-node replay fixture (every path crosses the simulated fire) is the correct outcome.
awaiting: user response

## Tests

### 1. Domain review of AOI-boundary exits and route suitability for Bandipur
expected: Operator accepts the AOI-boundary exit policy for the MVP and agrees the replay fixture's "blocked" route is correct (the demo never shows a "safe" route on this synthetic graph).
result: [pending]

### 2. Replay demo uses Groq with the operator's own key
expected: With LLM_ENABLED=true and LLM_PROVIDER=groq set, `.venv\Scripts\python.exe scripts\replay_demo.py` prints `LLM Fallback : No`, a draft plan, and 8 audit entries.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
