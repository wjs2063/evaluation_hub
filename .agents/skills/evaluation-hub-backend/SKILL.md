---
name: evaluation-hub-backend
description: Build, modify, review, debug, or verify EvaluationHub's async FastAPI APIs, AsyncSession and SQLModel persistence, Alembic migrations, authentication and ownership rules, external endpoint security, evaluator orchestration, OpenAPI contracts, and uv-based backend tests. Use for backend-only work or the backend portion of a full-stack EvaluationHub change.
---

# EvaluationHub Backend

Develop EvaluationHub APIs and persistence as non-blocking, secure, auditable vertical slices.

## Load context

1. Read `$evaluation-hub` shared architecture and evaluation-domain references.
2. Read `references/backend.md` before changing APIs, persistence, security, migrations, external calls, generated-client contracts, or backend tests.
3. Read `$evaluation-hub-deepeval` and its applicable official-document references before changing any DeepEval import, metric, test case, mapping, or execution path.
4. Load `$evaluation-hub-frontend` when a public request or response contract changes.

## Work a backend vertical slice

1. Trace the handler, authorization dependency, service or evaluator boundary, SQLModel schema, Alembic revision, response model, and focused tests.
2. Use `async def` at I/O boundaries and ordinary `def` for pure parsing, normalization, scoring, serialization, mapping, and validation.
3. Use the shared async engine, request-scoped `AsyncSession`, and `SessionDep`; await every database operation.
4. Keep transactions short and do not hold one open during external model or judge calls.
5. Preserve per-row or per-turn score, reason, error, and execution evidence.

## Synchronize public contracts

Treat a public API change as one vertical slice: update backend models and operations, generate OpenAPI, regenerate the frontend client, and update frontend consumers and tests. Never hand-edit generated client files.

## Protect boundaries

- Require the correct authenticated owner or superuser dependency.
- Never trust a browser-supplied owner ID.
- Never expose, log, or persist plaintext endpoint headers or API keys.
- Retain POST-only outbound calls, URL and origin validation, SSRF defenses, timeouts, response-size limits, row limits, and concurrency limits.
- Never silently fall back from DeepEval or another selected evaluator to `local`.

## Verify

Run all Python commands through `uv run`. Use focused evaluation tests, async behavior tests, backend static checks, and foundation regressions in proportion to the change. Report missing PostgreSQL, model credentials, or external services separately from assertion failures.

## Example prompt

```text
$evaluation-hub-backend 멀티턴 실행 API의 소유권과 SSRF 방어를 유지하면서 비동기 영속성 경로를 수정해줘.
```
