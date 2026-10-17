---
last_mapped_commit: 568fe4ddfb5bf5d575995eb03ee89ffbeefc939f
last_mapped_at: 2026-10-14
---
# Testing Patterns

**Analysis Date:** 2026-10-14

## Test Framework

**Runner:**
- `pytest==8.4.2`, configured in the root `pyproject.toml`.
- Assertion library: pytest's built-in assertions and `pytest.raises`; no separate assertion library is configured.
- Root pytest configuration adds each workspace `src/` directory to `pythonpath` and registers one marker: `compose` (requires local Docker Compose services).

**Run Commands:**

```bash
uv sync --locked
uv run pytest tests/unit -q                       # CI unit suite
uv run pytest tests/integration -m compose -q     # Compose integration suite; set COMPOSE_SMOKE=1 and DATABASE_URL
uv run pytest -q                                  # Discover the repository's test files locally
uv run ruff check .                               # Repo-wide lint gate
uv run mypy packages/wildfire_core                # CI type-check gate
```

The exact CI commands and Compose environment are defined in `.github/workflows/ci.yml`. Integration tests are skipped unless `COMPOSE_SMOKE=1`; the CI Compose job starts services, applies migrations, sets `DATABASE_URL` and `REDIS_URL`, and tears Compose down afterward.

## Test File Organization

**Location:**
- Most application-wide unit tests are in `tests/unit/`; Compose integration tests are in `tests/integration/`.
- Some packages keep tests beside the package directory rather than in the root test tree: `apps/agents/fire/tests/`, `apps/ingest_worker/tests/`, and `packages/wildfire_core/tests/`.
- CI explicitly invokes only `tests/unit` and `tests/integration`; the package-local suites are discoverable with repository-wide pytest discovery but are not explicit CI test targets.

**Naming:**
- Name files `test_<area>.py` and test functions `test_<behavior>()`, for example `tests/unit/test_triggers.py` and `apps/agents/fire/tests/test_ca_model.py`.
- Most tests have `-> None` return annotations, though some package-local tests do not. Prefer annotated tests to align with strict typing conventions.

**Structure:**

```text
tests/
  fixtures/
    firms/
    open_meteo/
  unit/
  integration/
apps/<package>/tests/
packages/<package>/tests/
```

## Test Structure

**Suite Organization:**

```python
def test_threshold_must_be_positive() -> None:
    with pytest.raises(ValueError):
        evaluate_new_hotspot(1, 0)
```

This is the pattern in `tests/unit/test_triggers.py`: focused functions, direct assertions, and `pytest.raises` for invalid-input contracts.

**Patterns:**
- Test named behaviors and edge boundaries directly. `tests/unit/test_freshness.py` checks fresh, stale, and unavailable classifications; `tests/unit/test_config_and_geo.py` checks both containment and invalid bounds.
- For deterministic safety-critical behavior, use fixed inputs/seeds and assert repeatability, as in `apps/agents/fire/tests/test_ca_model.py` and `tests/unit/test_determinism.py`.
- Assert contract properties at boundaries: Pydantic `ValidationError`, required fields, enum/literal values, and numeric ranges appear in `tests/unit/test_fire_contracts.py` and `packages/wildfire_core/tests/test_phase2_schemas.py`.
- Keep each test independent and use explicit timestamps/`SimClock` for freshness and ingestion behavior instead of relying on current wall-clock time; see `tests/unit/test_clock.py` and `tests/unit/test_firms_parser.py`.

## Integration Markers and External Services

- `compose` is the only marker registered in root `pyproject.toml`. Apply both `@pytest.mark.compose` and an environment-based `skipif` to tests requiring live Compose services, following `tests/integration/test_compose_foundation.py` and `tests/integration/test_migrations_and_ingest.py`.
- Integration tests exercise the FastAPI test client, PostgreSQL schema/migrations, idempotent ingestion, trigger persistence, and shared-state persistence. They use a real `DATABASE_URL` and dispose created SQLAlchemy engines.
- The Compose CI job runs `docker compose up -d --build --wait`, upgrades Alembic to head, then invokes `pytest tests/integration -m compose -q` with `COMPOSE_SMOKE=1` (`.github/workflows/ci.yml`).
- `REDIS_URL` is provided by CI's Compose job; the current integration examples principally assert API readiness and PostgreSQL state.

## Fixtures and Factories

**Test Data:**

```python
payload = Path("tests/fixtures/firms/hotspot_sample.csv").read_text()
observations = parse_firms_csv(
    payload, SimClock(datetime(2026, 1, 1, 12, tzinfo=UTC)), origin="replay"
)
```

This pattern from `tests/unit/test_firms_parser.py` loads a checked-in realistic fixture and supplies a fixed simulation clock. JSON fixtures are loaded with `json.loads`, as in `tests/unit/test_weather_parser.py`.

**Location:**
- Shared input and expected-output data are in `tests/fixtures/firms/` and `tests/fixtures/open_meteo/`.
- Small object factories are local private helpers, such as `_input` in `tests/unit/test_fire_contracts.py`.
- Tests do not currently define pytest fixture functions, shared conftest helpers, or a common fixture-factory module.

## Mocking

**Framework:**
- No mocking library or project-level mocking pattern is configured. Current tests favor pure functions, fixed data, `SimClock`, and real Compose services for integration coverage.

**Guidance:**
- Prefer injected clocks and pure boundaries over patching time or implementation internals.
- Use live external services only in the explicitly marked Compose integration suite; keep ordinary unit tests service-independent.

## Coverage

**Requirements:**
- No coverage plugin, coverage configuration, minimum percentage, or coverage-report command is configured in `pyproject.toml` or `.github/workflows/ci.yml`.
- `hypothesis` is in the root development dependency group, but no property-based test usage is visible in the repository's tests.

**Visible coverage gaps:**
- CI does not run package-local suites under `apps/agents/fire/tests/`, `apps/ingest_worker/tests/`, or `packages/wildfire_core/tests/`; add those paths to the unit test gate or consolidate them under the existing root test command.
- CI runs mypy only for `packages/wildfire_core`, although strict mode is configured globally and application packages are also in scope for the root Ruff check.
- No configured coverage report means CI cannot report or enforce gaps by module. Prioritize coverage around parser malformed-input handling, service/database failure paths, and the deterministic/safety validation boundaries as those evolve.

## Test Types

**Unit Tests:**
- Exercise parsing, validation, geometry/config boundaries, freshness, triggers, deterministic outputs, and schemas using fixed data in `tests/unit/` and package-local `tests/` directories.

**Integration Tests:**
- Exercise Compose-backed API and database/migration behavior in `tests/integration/`; gate with the `compose` marker and `COMPOSE_SMOKE` variable.

**E2E Tests:**
- No separate browser or end-to-end test framework is configured. `tests/integration/test_compose_foundation.py` is the broadest current service-level smoke test.

## Common Patterns

**Async Testing:**
- No async pytest plugin or async test pattern is configured; existing tests are synchronous.

**Error Testing:**

```python
with pytest.raises(ValidationError):
    BBox.from_value("77.3,11.5,76.0,12.4")
```

Use `pytest.raises` for expected validation/domain failures, as in `tests/unit/test_config_and_geo.py`. One existing config test uses explicit `try`/`except` plus `AssertionError` in `tests/unit/test_config.py`; prefer the pytest context-manager form for new tests.

---

*Testing analysis: 2026-10-14*
