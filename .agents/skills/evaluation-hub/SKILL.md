---
name: evaluation-hub
description: Build, modify, review, debug, or verify EvaluationHub, the repository's async-first FastAPI and React application for AI response evaluation. Use for EvaluationHub evaluation datasets, managed model endpoints, single-turn and multi-turn live tests, regression and baseline comparisons, evaluator integrations, result UX, authentication-aware UI, async API contracts, asynchronous SQLModel persistence, Alembic migrations, generated clients, uv-based Python workflows, and repository-specific tests. Also use for frontend console UI work in this repository. Do not use for unrelated generic FastAPI or React projects.
---

# EvaluationHub

Develop EvaluationHub as an AI evaluation product while preserving the proven FastAPI Full Stack Template foundation.

## Load context

1. Read `references/architecture.md` for every task.
2. Read `references/evaluation-domain.md` for evaluation behavior, models, metrics, runs, integrations, or result UX.
3. Read `references/backend.md` for APIs, persistence, security, migrations, evaluator execution, or generated-client changes.
4. Read `references/frontend.md` for routes, components, navigation, forms, themes, responsive behavior, or Playwright work.
5. Read `references/example-prompts.md` only when explaining or testing skill usage.

## Work a vertical slice

1. Inspect `git status --short`; preserve unrelated and pre-existing changes.
2. Classify the request as template foundation, EvaluationHub domain, or both.
3. Trace the smallest complete path: route or component → request contract → FastAPI handler → SQLModel and migration → focused tests.
4. State assumptions only when they affect evaluation meaning, security, persistence, or compatibility.
5. Implement the smallest coherent change. Avoid broad template rewrites and speculative abstractions.

## Preserve product invariants

- Keep authentication, ownership filtering, superuser boundaries, password flows, health checks, and generated OpenAPI workflow intact.
- Make evaluation runs reproducible: store inputs, expected and actual outputs, evaluator, scores, reasons, errors, timestamps, and baseline relationships where applicable.
- Keep pass/fail derived from the configured threshold. Display score meaning and evaluator availability explicitly.
- Preserve row- or turn-level evidence when summarizing a run. Do not hide partial failures behind aggregate scores.
- Treat endpoint headers and API keys as secrets. Never return plaintext secrets, log them, or persist them unencrypted.
- Keep outbound evaluation calls POST-only and retain URL validation, SSRF defenses, timeouts, response-size limits, row limits, and concurrency limits.
- Treat unavailable integrations as unavailable capabilities, not successful evaluations. `local` works without external credentials; DeepEval requires its package and an OpenAI key; Langfuse is not implemented yet.
- Add migrations for persisted schema changes. Do not edit generated migration history to retrofit a new change.

## Use async at I/O boundaries

- Choose `async def` by behavior, not by naming convention: use it when the function awaits database, network, filesystem, queue, subprocess, timer, or other asynchronous work.
- Keep every I/O-bearing FastAPI route, dependency, CRUD operation, service, and integration path asynchronous.
- Use the shared async engine, `AsyncSession`, and `SessionDep`. Await every database execution, lookup, flush, commit, refresh, rollback, and delete operation.
- Never introduce synchronous SQLAlchemy sessions, `create_engine`, `session.query`, blocking database drivers, or un-awaited SQLModel operations.
- Use `httpx.AsyncClient` for outbound requests. Move unavoidable blocking SDK, model-evaluator, password-hashing, or CPU-heavy calls to an AnyIO worker thread.
- Use normal `def` for pure parsing, normalization, scoring, serialization, mapping, and validation that performs no I/O and has nothing to await.
- Do not turn pure helpers into coroutines merely to make the codebase look uniformly asynchronous. Avoid meaningless `await` chains and coroutine overhead.
- Never share one `AsyncSession` across concurrent tasks. Keep transactions short and avoid holding one open during external model calls.
- Write async I/O tests with pytest AnyIO, `httpx.AsyncClient`, `ASGITransport`, and async fixtures. Test pure functions with ordinary synchronous tests.
- Run Python dependencies, servers, migrations, linters, type checks, scripts, and tests through `uv run`; do not invoke environment-dependent `python`, `pip`, `pytest`, `alembic`, or `fastapi` executables directly.

## Keep contracts synchronized

- Update backend models and response schemas before consumers when changing an API.
- Regenerate the frontend client after OpenAPI changes; do not hand-edit `frontend/src/client/*.gen.ts` or `frontend/src/routeTree.gen.ts`.
- Preserve existing routes, payloads, product copy, accessible names, and `data-testid` values unless the request explicitly changes them.
- Extend shared UI primitives and design tokens before adding route-specific duplication.

## Verify proportionally

Run the repository helper from the root:

```bash
.agents/skills/evaluation-hub/scripts/verify_project.sh frontend
.agents/skills/evaluation-hub/scripts/verify_project.sh backend-static
.agents/skills/evaluation-hub/scripts/verify_project.sh async-tests
.agents/skills/evaluation-hub/scripts/verify_project.sh evaluation-tests
.agents/skills/evaluation-hub/scripts/verify_project.sh backend-tests
```

Use `ui` only with the frontend already running through `npm run dev` at port 5173. Run extra feature-specific tests for touched authentication, Items, Users/Admin, Settings, or evaluation flows.

Separate implementation failures from missing database, browser, model credentials, or external endpoint prerequisites. Never weaken tests to make checks pass.

## Report

Lead with the user-visible or API outcome. List important files, checks run, and unresolved prerequisites. Distinguish automated verification from manual visual inspection.
