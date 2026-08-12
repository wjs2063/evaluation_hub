# Backend conventions

## Use repository locations

- Use `backend/app/main.py` for application assembly and `backend/app/api/main.py` for API registration.
- Use `backend/app/api/routes/evaluations.py` for current evaluation orchestration.
- Use `backend/app/api/deps.py` for authentication and authorization dependencies.
- Use `backend/app/models.py` for SQLModel tables and public API schemas.
- Use `backend/app/core/config.py` for settings and `backend/app/core/security.py` for encryption and credential helpers.
- Add migrations under `backend/app/alembic/versions/`.
- Add evaluation coverage under `backend/app/tests/api/routes/test_evaluations.py` and foundation coverage under `backend/tests/`.

## Keep I/O asynchronous

| Work | Form | Examples |
| --- | --- | --- |
| Awaitable I/O | `async def` | FastAPI handlers, database CRUD, HTTP clients, async SDKs, timers |
| Pure computation | `def` | Parsing, normalization, score math, mapping, serialization, validation |
| Blocking SDK or heavy CPU work | worker-thread call | Only APIs without a supported async method |

- Create the application engine with `sqlalchemy.ext.asyncio.create_async_engine`.
- Pass request-scoped `sqlmodel.ext.asyncio.session.AsyncSession` through `SessionDep`.
- Use SQLModel or SQLAlchemy `select`, `update`, and `delete` statements and await `session.exec(...)`.
- Await `get`, `flush`, `commit`, `refresh`, `rollback`, and `delete` operations.
- Never introduce `sqlalchemy.orm.Session`, `sqlmodel.Session`, `create_engine`, `session.query`, a synchronous database driver, or blocking raw SQL into application code.
- Never share one `AsyncSession` across concurrent tasks.
- Persist state before an external call and persist the result afterward through an explicit success or failure path.
- Use `httpx.AsyncClient` for outbound endpoints.
- Prefer a supported async SDK or evaluator method. Isolate only incompatible synchronous calls with `anyio.to_thread.run_sync` or an equivalent AnyIO worker-thread boundary.
- Use asynchronous password helpers already provided by `app.core.security`.
- Never call `time.sleep(...)` in request or background-task paths.

Treat synchronous `backend/app/alembic/env.py` as migration-tooling debt, not an application pattern. When changing it, use `async_engine_from_config` and run synchronous migration callbacks through `await connection.run_sync(...)`.

## Enforce authentication and ownership

- Mount application endpoints below `settings.API_V1_STR`, currently `/api/v1`.
- Require `CurrentUser` for owner-scoped evaluation resources.
- Require `CurrentSuperuser` to create, update, or disable managed endpoints.
- Filter datasets, scenarios, and runs by authenticated owner.
- Return public response models that omit encrypted headers and internal secret material.
- Preserve existing paginated `{ data, count }` contracts.

## Protect outbound calls and secrets

- Validate endpoint URLs and reject embedded credentials.
- Block loopback, link-local, private, multicast, reserved, and otherwise unsafe resolved addresses unless an explicit trusted-network design replaces the policy.
- Resolve scenario-turn URLs against the managed endpoint and prevent origin escape.
- Use configured timeouts, concurrency semaphore, response-size cap, and execution-row cap.
- Reject sensitive per-turn header overrides and use encrypted managed-endpoint headers for credentials.
- Keep requests POST-only. Treat persisted legacy `method` columns as compatibility fields, not public configuration.
- Never return plaintext secrets, log them, or store them without the repository encryption boundary.

## Preserve evaluation persistence

- Commit run metadata and row or turn evidence coherently so saved runs remain auditable.
- Preserve evaluator identity, metric name, score, reason, error, input, expected output, actual output, status, timestamp, and baseline relationship where applicable.
- Preserve cascade behavior for owners, datasets, scenarios, rows, turns, and runs.
- Add a new Alembic revision for schema changes and test upgrades against existing-data assumptions.
- Never rewrite an existing migration after it may have shipped.
- Never silently replace an unavailable DeepEval evaluator with `local`.

## Synchronize OpenAPI consumers

After changing a public schema or operation:

1. Update backend models and handlers.
2. Obtain OpenAPI through the repository's client-generation workflow.
3. Run `scripts/generate-client.sh` or `npm run generate-client` from the appropriate directory.
4. Review generated changes under `frontend/src/client/`.
5. Update React consumers and TypeScript or Playwright contracts.

Never edit generated client or schema files by hand.

## Verify with uv

- Synchronize backend development dependencies with `uv sync --package app --group dev` when required.
- From `backend/`, use `uv run <tool>`; from the repository root, use `uv run --package app <tool>`.
- Run Ruff, mypy, and ty through the repository verifier or their existing uv commands.
- Run `backend/app/tests/api/routes/test_evaluations.py` for evaluation behavior.
- Run `backend/tests/test_async_behavior.py` for async regressions and `backend/tests/` for foundation regressions.
- Use pytest AnyIO, `httpx.AsyncClient`, `ASGITransport`, async fixtures, and independent sessions for I/O tests.
- Keep pure parser, scorer, serializer, and validator tests synchronous.
- Report a missing PostgreSQL service separately from application failures.
