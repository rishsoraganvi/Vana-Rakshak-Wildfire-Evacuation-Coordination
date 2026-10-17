---
phase: 02-mvp-detection-to-route
plan: 08
subsystem: deployment-config
tags: [docker-compose, security, credentials, ci, gap-closure, HI-06]
requires: [02-06]
provides:
  - "docker-compose.yml publishes postgres and redis on 127.0.0.1 only"
  - "Required ${POSTGRES_PASSWORD:?...} for the postgres service and the api DATABASE_URL; no default password"
  - "Password-free config/defaults.yaml database_url and empty Settings.postgres_password default"
  - "CI compose-smoke job with its own ephemeral POSTGRES_PASSWORD"
  - "Offline regression tests guarding loopback bindings and absence of a default credential"
affects: []
tech-stack:
  added: []
  patterns: ["required-variable interpolation in compose", "yaml-parsed compose assertions in the unit job"]
key-files:
  created:
    - tests/unit/test_compose_bindings.py
  modified:
    - docker-compose.yml
    - .github/workflows/ci.yml
    - config/defaults.yaml
    - packages/wildfire_core/src/wildfire_core/config.py
    - tests/unit/test_config.py
key-decisions:
  - "Settings.postgres_password field and its _ENV_MAP entry stay (extra=forbid would reject POSTGRES_PASSWORD in .env); only the default changes to an empty SecretStr"
  - "Redis AUTH and alembic.ini placeholder URL remain out of scope (T-02-08-04, T-02-08-06 accepted)"
requirements-completed: []
status: complete
completed: 2026-10-17
actuals:
  tokens: 6000
  tasks: 2
  commits: 4
---

# Phase 2 Plan 08: Loopback-only Postgres/Redis and required password (HI-06) Summary

Postgres and Redis now publish only on 127.0.0.1, Compose refuses to start without an explicit POSTGRES_PASSWORD, and no database password remains in compose, config/defaults.yaml, or Settings defaults.

## Tasks

| # | Task | Commits |
|---|------|---------|
| 1 | Tracer: loopback ports, required password, CI ephemeral password, offline guard test | 332f2e9 (RED), a81f2b7 |
| 2 | Remove default DB credential from app config | 33ba117 (RED), db50406 |

## What changed

- docker-compose.yml: postgres `127.0.0.1:${POSTGRES_PORT:-5432}:5432`, redis `127.0.0.1:${REDIS_PORT:-6379}:6379`; both `POSTGRES_PASSWORD` and api `DATABASE_URL` use `${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}`.
- ci.yml compose-smoke: job-level `POSTGRES_PASSWORD: ci-ephemeral-password`; pytest-step DATABASE_URL uses the same value. Unit job untouched.
- tests/unit/test_compose_bindings.py (3 tests, run in the CI unit job): every port starts with `127.0.0.1:`, password required in both places, no `POSTGRES_PASSWORD:-` default and no `change_me` in compose.
- config/defaults.yaml: `database_url: postgresql+psycopg://wildfire@postgres:5432/wildfire`; config.py: `postgres_password` default `SecretStr("")`.
- tests/unit/test_config.py: `test_default_settings_carry_no_database_password`, `test_database_url_env_overrides_defaults`.

## Verification

- RED confirmed before each GREEN (3 failed; 1 failed).
- `pytest tests/unit -q`: 21 passed. Full offline suite: 97 passed, 7 skipped. Ruff clean on apps/packages/scripts/tests; mypy on packages/wildfire_core/src: no issues.
- Acceptance greps: `POSTGRES_PASSWORD:-` 0, `127.0.0.1:` 3, `POSTGRES_PASSWORD:?` 2, `ci-ephemeral-password` 2, `change_me` 0 in defaults.yaml and config.py, llm_model line from 02-06 preserved.
- `docker compose config` (read-only, no containers touched): with POSTGRES_PASSWORD unset and an empty env file it exits 1 with "required variable POSTGRES_PASSWORD is missing a value"; with it set it exits 0 and rendered ports show `host_ip: 127.0.0.1` for api (8000), postgres (5432) and redis (6379). With the real environment, `docker compose config --quiet` exits 0, so POSTGRES_PASSWORD is available to Compose.
- Host check after load_dotenv: `DATABASE_URL set: True` (value not printed; .env not read or edited).

## Pending orchestrator restart

The running containers still hold the old 0.0.0.0 bindings. After the orchestrator restarts the stack (pgdata volume kept), verify:
- `docker compose port postgres 5432` prints `127.0.0.1:5432`
- `docker compose port redis 6379` prints `127.0.0.1:6379`
- `COMPOSE_SMOKE=1 .venv/Scripts/python.exe -m pytest tests/smoke -m smoke -q` and the compose-gated live tests still pass (DATABASE_URL from .env must match the live role password).
Not executed by me per the no-container-changes constraint.

## Deviations from Plan

**1. [Rule 3 - Blocking] ruff I001 on test_config.py imports** after adding imports; fixed with `ruff --fix` (the wildfire_core import joins the third-party block). Folded into commit db50406.

Otherwise the plan executed as written. The tracer's live recreate step was deferred to the orchestrator (user constraint).

## Known Stubs

None.

## Threat Flags

None. T-02-08-01..03 mitigated (tests guard them); T-02-08-04 (Redis AUTH), -05, -06 (alembic.ini placeholder URL with the old password) accepted per plan.

## Self-Check: PASSED

Files exist: tests/unit/test_compose_bindings.py, docker-compose.yml, ci.yml, defaults.yaml, config.py. Commits 332f2e9, a81f2b7, 33ba117, db50406 are in git log.
