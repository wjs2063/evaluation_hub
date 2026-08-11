# Architecture and provenance

## Product identity

EvaluationHub is a monolithic AI response evaluation application derived from the FastAPI Full Stack Template. Preserve the foundation, but make product decisions for AI evaluation rather than treating the repository as an untouched template.

## Foundation inherited from the template

- FastAPI API assembly under `backend/app/api/`
- AsyncEngine, AsyncSession, SQLModel, and PostgreSQL persistence
- Alembic migrations under `backend/app/alembic/versions/`
- JWT authentication, password recovery, users, superuser administration, and Items
- Pydantic settings, CORS validation, SMTP templates, Sentry boundary, and health checks
- React 19, TypeScript, Vite, TanStack Router/Query/Table, React Hook Form, and generated OpenAPI client
- Docker Compose definitions for PostgreSQL, backend, frontend, MailCatcher, Adminer, and Playwright
- pytest, Ruff, mypy, ty, Biome, and Playwright verification
- uv-managed Python dependencies and command execution

Do not remove or rename these foundation features merely because an evaluation task does not use them directly.

## EvaluationHub-owned areas

- `backend/app/api/routes/evaluations.py`: evaluation orchestration, integrations, datasets, endpoints, scenarios, and runs
- `backend/app/models.py`: persisted evaluation entities and public contracts
- Evaluation-related Alembic revisions
- `frontend/src/components/Evaluations/`: single-turn, multi-turn, live, regression, and result interfaces
- `frontend/src/routes/_layout/evaluation*.tsx`: evaluation routes
- `frontend/src/components/Admin/EvaluationEndpoints.tsx`: managed endpoint administration
- `frontend/tests/evaluation-details.spec.ts`: evaluation presentation coverage
- `examples/sample-evaluation.csv` and `examples/chat-openai-server/`: local evaluation fixtures

## Request flow

```text
React route/workspace
  → /api/v1/evaluations/*
  → authenticated FastAPI handler
  → endpoint/dataset/scenario validation
  → external model call or local evaluation
  → SQLModel run and row/turn persistence
  → aggregate plus evidence-rich response
  → result and baseline comparison UI
```

## Change strategy

- Trace vertical slices instead of editing only the visible layer.
- Keep compatibility when improving template-derived code.
- Prefer extracting focused services or adapters when evaluation orchestration grows; avoid a repository-wide architecture rewrite during a feature change.
- Keep the repository monolithic unless the user explicitly requests a deployment or service-boundary change.
