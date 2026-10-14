---
last_mapped_commit: 568fe4ddfb5bf5d575995eb03ee89ffbeefc939f
last_mapped_at: 2026-10-14
---
# Coding Conventions

**Analysis Date:** 2026-10-14

## Naming Patterns

**Files:**
- Use lowercase `snake_case.py` module names that describe the domain or operation, such as `apps/ingest_worker/src/ingest_worker/firms/parser.py` and `packages/wildfire_core/src/wildfire_core/db/repositories.py`.
- Tests use `test_*.py`, for example `tests/unit/test_firms_parser.py`.

**Functions:**
- Use `snake_case` for public and private functions. Prefix implementation helpers with `_`, as in `_number` and `_value` in `apps/ingest_worker/src/ingest_worker/firms/parser.py` and `apps/ingest_worker/src/ingest_worker/weather/parser.py`.
- Test functions start with `test_` and state a behavior or invariant, such as `test_freshness_boundaries_are_explicit` in `tests/unit/test_freshness.py`.

**Variables:**
- Use descriptive `snake_case` names for locals and parameters (`ingested_at`, `valid_time`, `payload`). Avoid abbreviations except established domain terms such as `aoi`, `frp`, and `bbox`.

**Types:**
- Use `PascalCase` for classes and schema models: `FireRunInput`, `Freshness`, and `SimClock` in `packages/wildfire_core/src/wildfire_core/schemas/fire.py`, `packages/wildfire_core/src/wildfire_core/schemas/metadata.py`, and `packages/wildfire_core/src/wildfire_core/clock.py`.
- Use `UPPER_SNAKE_CASE` for constants when needed; no broad constants convention is configured.

## Code Style

**Formatting:**
- Target Python 3.11 and a 100-character line length as configured in the root `pyproject.toml`.
- Ruff lint rules are `E`, `F`, `I`, `B`, and `UP`; follow those rules and let Ruff organize imports. CI runs `uv run ruff check .` from `.github/workflows/ci.yml`.
- No formatter configuration or format command is defined. Keep changes consistent with neighboring files rather than assuming a formatter is enforced.

**Linting and typing:**
- Add parameter and return annotations to functions. The root `pyproject.toml` configures mypy strict mode, though CI currently checks only `packages/wildfire_core`.
- For optional values, spell the union explicitly, such as `float | None`, and use built-in generics such as `list[HotspotObservation]`; see `apps/ingest_worker/src/ingest_worker/firms/parser.py`.
- Pydantic boundary models declare constraints with `Field`, `Literal`, and `ConfigDict`; reject unrecognized fields on safety-relevant contracts using `extra="forbid"`, as in `packages/wildfire_core/src/wildfire_core/schemas/fire.py`.

## Import Organization

**Order:**
1. `from __future__` imports, when needed for annotations.
2. Python standard library imports.
3. Third-party dependencies.
4. Workspace packages and application modules.

For example, `apps/ingest_worker/src/ingest_worker/firms/parser.py` places `csv`, `io`, and `datetime` before `wildfire_core` imports. Keep import groups separated by blank lines; Ruff's `I` rules check ordering.

**Path Aliases:**
- No import aliases are configured. Workspace packages are made importable for pytest through the `pythonpath` entries in the root `pyproject.toml`.

## Error Handling

- Reject invalid domain inputs explicitly with `ValueError` or typed validation errors rather than silently coercing them. `apps/ingest_worker/src/ingest_worker/triggers.py` rejects a non-positive threshold; Pydantic schema validation in `packages/wildfire_core/src/wildfire_core/schemas/fire.py` raises `ValueError` for unsupported horizons.
- Use Pydantic `ValidationError` at model boundaries and test invalid inputs with `pytest.raises`, as in `tests/unit/test_fire_contracts.py` and `tests/unit/test_config_and_geo.py`.
- Do not swallow broad exceptions in new code. `apps/api_gateway/src/api_gateway/health.py` currently catches `Exception` around dependency readiness checks; preserve the endpoint's failure-to-unready behavior if modifying it, but prefer catching the narrow expected exception in new handlers.
- Keep required-data failures explicit; `apps/agents/weather/src/agent_weather/agent.py` raises `RuntimeError` when no weather observations are available.
- No project-wide logging convention or configured logging framework is present; avoid adding ad hoc logging without matching the owning module's established interface.

## Function Design

**Size:**
- Keep parsing, validation, and persistence responsibilities in their corresponding modules. For example, `apps/ingest_worker/src/ingest_worker/firms/parser.py` converts source rows into typed observations while the sibling `service.py` owns ingest behavior.

**Parameters:**
- Use keyword-only parameters for optional behavioral choices where it improves call-site clarity; parsers expose `origin` after `*` in `apps/ingest_worker/src/ingest_worker/firms/parser.py` and `apps/ingest_worker/src/ingest_worker/weather/parser.py`.
- Inject time through the `Clock` abstraction instead of reading wall-clock time inside deterministic parsing logic; see `packages/wildfire_core/src/wildfire_core/clock.py` and the parser tests in `tests/unit/test_firms_parser.py`.

**Return Values:**
- Return typed domain objects and explicit collections rather than loosely shaped dictionaries at shared boundaries. `parse_firms_csv` returns `list[HotspotObservation]`; Pydantic schemas in `packages/wildfire_core/src/wildfire_core/schemas/` define shared contracts.
- Keep safety-critical computations deterministic and validate their output contracts. Seeded simulation and repeatability are exercised in `apps/agents/fire/tests/test_ca_model.py` and `tests/unit/test_determinism.py`.

## Module Design

**Exports:**
- Keep implementation close to its domain package under `src/<package>/`; application modules use `apps/`, while shared contracts and infrastructure abstractions live in `packages/wildfire_core/src/wildfire_core/`.
- Prefer explicit imports from the owning module. Package `__init__.py` files exist, but a broad barrel-export convention is not established.

**Schema and safety boundaries:**
- Put cross-package data contracts in `packages/wildfire_core/src/wildfire_core/schemas/`; express enums/literal values, numeric bounds, tuple lengths, and extra-field policy in the schema itself.
- Keep generated or model-authored language from becoming an unvalidated numeric/safety decision. The project scope recorded in `.planning/STATE.md` requires deterministic validated numeric outputs and human approval before dissemination.

---

*Convention analysis: 2026-10-14*
