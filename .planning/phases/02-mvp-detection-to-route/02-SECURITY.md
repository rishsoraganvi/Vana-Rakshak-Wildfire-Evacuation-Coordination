---
phase: 02
slug: mvp-detection-to-route
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-10-17
---

# Phase 02 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Register source: `<threat_model>` blocks of gap-closure plans 02-04..02-09 plus their SUMMARY threat flags.
> Plans 02-01..02-03 were authored before threat modelling and carry no register; their surfaces
> (API, coordinator, ingest) are partly covered by the 02-08/02-06 controls below and by 02-REVIEW.md.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Host network → Compose services | Postgres, Redis and API ports published on the developer machine | DB credentials, incident/plan/audit data |
| Coordinator → Groq API | Optional LLM rationale call over the internet | Compact numeric incident metrics (no geometry), API key |
| Weather/hotspot rows → Coordinator | DB rows (live, replay, test origins) feeding deterministic models | Weather observations, hotspots |
| Fire/routing computation → plan/API consumers | Safety-relevant numbers surfaced to reviewers | Perimeters, routes, risk classifications |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-02-04-01 | Tampering (integrity) | Fire CA wind kernel | high | mitigate | FROM→downwind conversion in one place (`ca_model.py:26`); direction tests | closed |
| T-02-04-02 | Tampering (integrity) | Spread metrics / schema | high | mitigate | `_spread_metrics` front-advance over real horizon; `spread_direction_deg: float \| None` (`phase2.py:69-76`) | closed |
| T-02-04-03 | Denial of Service | CA settings | low | accept | Values come from repo config (LO-01 deferred) | closed |
| T-02-04-SC | Tampering | Supply chain | low | accept | No dependency changes | closed |
| T-02-05-01 | Tampering (integrity) | Edge fire exposure | high | mitigate | Full edge geometry `intersects` (`costs.py:16-64`); fixture probe now "blocked" | closed |
| T-02-05-02 | Tampering (integrity) | Router ranking | high | mitigate | Two-phase Dijkstra, finite fallback factor, `nearest_node_outside` (`router.py:16-122`) | closed |
| T-02-05-03 | Denial of Service | Router | low | accept | See 02-05-PLAN.md threat register | closed |
| T-02-05-04 | Tampering | Router | low | accept | See 02-05-PLAN.md threat register | closed |
| T-02-05-SC | Tampering | Supply chain | low | accept | No dependency changes | closed |
| T-02-06-01 | Information Disclosure | Groq adapter gating | high | mitigate | Ordered gates before any `Groq(` construction (`groq_adapter.py:129-152`); `ForbiddenGroq` tests | closed |
| T-02-06-02 | Information Disclosure | Model metadata / logs | high | mitigate | Explicit metadata field list; errors record class name only; key-not-in-metadata test | closed |
| T-02-06-03 | Repudiation | Audit trail | medium | mitigate | `model_metadata` on every rationale path, persisted via `_audit` (`graph.py:455`) | closed |
| T-02-06-04 | Tampering | Audit flush | medium | mitigate | `json.dumps` before `CAST(... AS jsonb)` (`audit.py:26-44`) | closed |
| T-02-06-05 | Tampering | Audit API exposure | medium | accept | API is loopback-only (`docker-compose.yml:42`) | closed |
| T-02-06-06 | Denial of Service | LLM latency | low | accept | See 02-06-PLAN.md threat register | closed |
| T-02-06-SC | Tampering | Supply chain (groq SDK) | low | accept | groq 1.7.0 pinned in `uv.lock`; no lock changes | closed |
| T-02-07-01 | Tampering (integrity) | Multi-cluster routing | high | mitigate | Union of all clusters' current + P50-1h perimeters penalises routing (`graph.py:85-90,318-331`) | closed |
| T-02-07-02 | Tampering (integrity) | Route origin / blocked choice | high | mitigate | Origin from `nearest_node_outside` with warnings; least-exposure ranking (`graph.py:93-105,334-391`) | closed |
| T-02-07-03 | Denial of Service | Per-cluster CA cost | medium | accept | See 02-07-PLAN.md threat register | closed |
| T-02-07-04 | Repudiation | Plan record | medium | mitigate | `fire_results` min_length=1, persisted (`phase2.py:124`, `graph.py:470`) | closed |
| T-02-07-SC | Tampering | Supply chain | low | accept | No dependency changes | closed |
| T-02-08-01 | Information Disclosure / Tampering | Postgres port | high | mitigate | `127.0.0.1:` binding (`docker-compose.yml:11`); `test_compose_bindings.py`; live `docker compose port` → 127.0.0.1 (verified 2026-10-17) | closed |
| T-02-08-02 | Tampering / Elevation | Redis port | high | mitigate | `127.0.0.1:` binding (`docker-compose.yml:25`); same tests; live binding verified | closed |
| T-02-08-03 | Spoofing | Postgres credential | high | mitigate | `${POSTGRES_PASSWORD:?...}` required; no default password in config/Settings; CI supplies its own (fixed in 1c2096c) | closed |
| T-02-08-04 | Elevation of Privilege | Redis no AUTH | medium | accept | Loopback-only binding | closed |
| T-02-08-05 | Information Disclosure | CI ephemeral password | low | accept | Ephemeral CI DB, `down -v` in same job | closed |
| T-02-08-06 | Information Disclosure | `alembic.ini` placeholder | low | accept | `change_me` placeholder overridden by `DATABASE_URL` in `env.py:16-18` | closed |
| T-02-08-SC | Tampering | Supply chain | low | accept | No dependency changes | closed |
| T-02-09-01 | Spoofing / Tampering | Weather lookup | high | mitigate | Scoped query by location, provider, origin, time; bound params (`agent.py:33-56`, `graph.py:209-220`) | closed |
| T-02-09-02 | Tampering (integrity) | Weather fabrication | high | mitigate | No synthetic snapshot; no plan persisted without weather (`graph.py:223-229`) | closed |
| T-02-09-03 | Tampering (integrity) | NULL coercion | high | mitigate | IS NOT NULL filters, no `or 0.0`, `LookupError` (`agent.py:40-115`) | closed |
| T-02-09-04 | Denial of Service | Weather query | medium | accept | See 02-09-PLAN.md threat register | closed |
| T-02-09-SC | Tampering | Supply chain | low | accept | No dependency changes | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01 | T-02-04-03 | CA numeric settings from repo config; bounds deferred (LO-01) | Plan 02-04 register | 2026-10-17 |
| AR-02 | T-02-04-SC | No new dependencies | Plan 02-04 register | 2026-10-17 |
| AR-03 | T-02-05-03 | Low-severity DoS on routing; local prototype | Plan 02-05 register | 2026-10-17 |
| AR-04 | T-02-05-04 | Low-severity routing tampering residual | Plan 02-05 register | 2026-10-17 |
| AR-05 | T-02-05-SC | No new dependencies | Plan 02-05 register | 2026-10-17 |
| AR-06 | T-02-06-05 | Audit API readable without auth; loopback-only until Phase 4 JWT | Plan 02-06 register | 2026-10-17 |
| AR-07 | T-02-06-06 | LLM latency bounded by timeout; deterministic fallback | Plan 02-06 register | 2026-10-17 |
| AR-08 | T-02-06-SC | groq SDK pinned in lockfile | Plan 02-06 register | 2026-10-17 |
| AR-09 | T-02-07-03 | Per-cluster CA cost grows with clusters; acceptable at MVP scale | Plan 02-07 register | 2026-10-17 |
| AR-10 | T-02-07-SC | No new dependencies | Plan 02-07 register | 2026-10-17 |
| AR-11 | T-02-08-04 | Redis has no AUTH; loopback-only binding | Plan 02-08 register | 2026-10-17 |
| AR-12 | T-02-08-05 | CI uses an ephemeral literal password, destroyed with the job | Plan 02-08 register | 2026-10-17 |
| AR-13 | T-02-08-06 | `alembic.ini` keeps a placeholder URL; runtime uses `DATABASE_URL` | Plan 02-08 register | 2026-10-17 |
| AR-14 | T-02-08-SC | No new dependencies | Plan 02-08 register | 2026-10-17 |
| AR-15 | T-02-09-04 | Weather query cost; indexed, small table at MVP scale | Plan 02-09 register | 2026-10-17 |
| AR-16 | T-02-09-SC | No new dependencies | Plan 02-09 register | 2026-10-17 |

*Accepted risks do not resurface in future audit runs.*

**Tracked residual risks (non-blocking, from audit and 02-REVIEW-GAPS.md):** demo forces `LLM_ENABLED=true` unless set (WR-05); moved route origin not recorded in `RouteResult` and `nearest_node_outside` ignores connectivity (WR-08/WR-09); `get_weather_snapshot` origin/provider default to None and no max age (WR-02); password not URL-encoded in compose `DATABASE_URL` (WR-06).

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-17 | 33 | 33 | 0 | gsd-security-auditor (ASVS L1, block_on high) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-17
