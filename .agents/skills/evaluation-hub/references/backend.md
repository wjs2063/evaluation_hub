# Backend conventions

## Stack and locations

- FastAPI entry: `backend/app/main.py`
- API registration: `backend/app/api/main.py`
- Evaluation API: `backend/app/api/routes/evaluations.py`
- Dependencies and authorization: `backend/app/api/deps.py`
- SQLModel tables and API schemas: `backend/app/models.py`
- Settings: `backend/app/core/config.py`
- Secret encryption: `backend/app/core/security.py`
- Migrations: `backend/app/alembic/versions/`
- Evaluation tests: `backend/app/tests/api/routes/test_evaluations.py`
- Template API tests: `backend/tests/`

## Async I/O and synchronous pure computation

Select the function form from its actual work:

| Work | Form | Examples |
| --- | --- | --- |
| Awaitable I/O | `async def` | FastAPI handlers, DB CRUD, HTTP clients, async SDKs, timers |
| Pure computation | `def` | Parsing, normalization, score math, mapping, serialization, validation |
| Short CPU work | `def` | Small deterministic transforms that do not block meaningfully |
| Blocking SDK or heavy CPU work | `def` executed in a worker thread | Synchronous evaluators, password hashing, expensive local computation |

Do not add `async def` to a function that has no asynchronous operation to await. Async-first means keeping I/O non-blocking; it does not mean making every function a coroutine.

- Create the application engine with `sqlalchemy.ext.asyncio.create_async_engine`.
- Provide request-scoped `sqlmodel.ext.asyncio.session.AsyncSession` instances through `SessionDep`.
- Define every route or dependency that performs I/O with `async def`.
- Use SQLModel/SQLAlchemy statements such as `select`, `update`, and `delete`; execute them with `await session.exec(...)`.
- Use `await session.get(...)`, `await session.flush()`, `await session.commit()`, `await session.refresh(...)`, `await session.rollback()`, and `await session.delete(...)` as applicable.
- Never add `sqlalchemy.orm.Session`, `sqlmodel.Session`, `create_engine`, `session.query`, a synchronous DB driver, or blocking raw SQL execution to application code.
- Pass `AsyncSession` explicitly to CRUD/service functions. Do not hide request sessions in globals.
- Do not share an `AsyncSession` between concurrently scheduled tasks. Use one session per request or independent background task.
- Keep database transactions short. Avoid keeping a transaction open while waiting for an external model endpoint or judge API; persist state before the call and persist results afterward with an explicit failure path.

Pure input parsing, deterministic scoring, URL validation, and response mapping should remain normal synchronous functions. Call them directly from async code without wrapping or awaiting them.

## Non-database blocking work

- Use `httpx.AsyncClient`, not `requests`, for external model endpoints.
- Await async SDK methods when available.
- Wrap unavoidable synchronous SDK or CPU-heavy calls with `anyio.to_thread.run_sync`. Keep arguments and return values explicit, and propagate cancellation/error state correctly.
- Use async password hashing/verification wrappers already provided by `app.core.security`.
- Use `await asyncio.sleep(...)` or AnyIO equivalents; never call `time.sleep(...)` in request or background-task paths.
- Apply concurrency limits around external evaluation work and do not serialize independent network waits accidentally.

## API boundaries

- Mount application endpoints below `settings.API_V1_STR`, currently `/api/v1`.
- Require `CurrentUser` for owner-scoped evaluation resources.
- Require `CurrentSuperuser` to create, update, or disable managed endpoints.
- Filter dataset, scenario, and run access by owner; never trust a browser-supplied owner ID.
- Return public models that omit encrypted headers and internal secret material.
- Preserve paginated `{ data, count }` contracts where already used.

## Outbound-call safety

- Validate endpoint URLs and reject credentials embedded in URLs.
- Retain DNS/IP checks that block loopback, link-local, private, multicast, reserved, and otherwise unsafe targets unless an explicit trusted-network design replaces them.
- Resolve turn URLs against the managed endpoint and prevent escaping its allowed origin.
- Use configured request timeouts, concurrency semaphore, response-size cap, and execution-row cap.
- Reject sensitive per-turn header overrides; use encrypted managed endpoint headers for credentials.
- Keep requests POST-only. The persisted legacy `method` columns are compatibility fields, not public configuration.

## Persistence

- Use async session operations consistently and await every database operation.
- Commit run metadata and row/turn evidence coherently so a saved run can be audited later.
- Preserve cascade behavior for owner, dataset, scenario, row, turn, and run lifecycles.
- Add a new Alembic revision for schema changes and test upgrades against existing data assumptions.
- Do not rewrite existing migration files after they may have shipped.

The current application runtime is async, but `backend/app/alembic/env.py` still constructs a synchronous migration engine. Treat this as migration-tooling technical debt. When changing that environment, migrate it to `async_engine_from_config` and run Alembic's synchronous migration callback through `await connection.run_sync(...)`; do not copy its synchronous engine pattern into application code.

## OpenAPI client

After changing public API schemas or operations:

1. Run the backend and obtain its OpenAPI document using the repository's client-generation workflow.
2. Run `scripts/generate-client.sh` or `npm run generate-client` from the appropriate directory.
3. Review generated changes under `frontend/src/client/`.
4. Update callers and TypeScript tests.

Never hand-edit generated client or schema files.

## Verification

- Install/synchronize backend development dependencies with `uv sync --package app --group dev` from the repository root when required.
- Run all Python commands through uv. From `backend/`, use `uv run <tool>`; from the repository root, use `uv run --package app <tool>`.
- Run static checks with `uv run ruff check app`, `uv run ruff format app --check`, `uv run mypy app`, and `uv run ty check app`.
- Run focused domain tests with `uv run pytest -q app/tests/api/routes/test_evaluations.py`.
- Run async behavior coverage with `uv run pytest -q tests/test_async_behavior.py`.
- Run foundation regressions with `uv run pytest -q tests`.
- Run migrations and the local API with `uv run alembic upgrade head` and `uv run fastapi dev`, respectively.
- Database-backed tests require the repository's configured PostgreSQL test environment. Report an unavailable database separately from assertion failures.

For tests that touch I/O:

- Set `pytestmark = pytest.mark.anyio` or mark the individual async test.
- Use `async def` test functions, `AsyncClient(transport=ASGITransport(app=app))`, and async fixtures.
- Use `AsyncSession` and awaited SQL statements for setup, assertions, and cleanup.
- Test concurrency with independent sessions and bounded task groups where relevant.
- Do not use synchronous `TestClient` or synchronous DB sessions as shortcuts.

Synchronous tests remain appropriate for pure parsers, score calculations, serializers, and validation helpers that do not perform I/O.
