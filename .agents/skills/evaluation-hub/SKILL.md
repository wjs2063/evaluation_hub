---
name: evaluation-hub
description: Route EvaluationHub work across the repository's React frontend, async FastAPI backend, and DeepEval integration while preserving shared architecture, evaluation-domain invariants, security boundaries, and verification workflows. Use for full-stack EvaluationHub changes, cross-layer reviews, or tasks whose owning specialist is not yet clear. Do not use for unrelated generic FastAPI or React projects.
---

# EvaluationHub

Route EvaluationHub work to the smallest set of role-specific skills while preserving shared product contracts.

## Load shared context

1. Read `references/architecture.md` for every task.
2. Read `references/evaluation-domain.md` for evaluation behavior, models, metrics, runs, integrations, or result UX.
3. Inspect `git status --short` and preserve unrelated or pre-existing changes.

## Route by responsibility

- Load `$evaluation-hub-backend` for FastAPI routes, SQLModel persistence, Alembic, authentication, ownership, outbound calls, OpenAPI, or backend tests.
- Load `$evaluation-hub-deepeval` for evaluator selection, DeepEval test-case mapping, judge execution, metric results, or any change that imports or configures DeepEval.
- Load `$evaluation-hub-frontend` for React routes, evaluation-console UX, generated-client consumption, responsive behavior, accessibility, or Playwright.
- Load every affected specialist for a cross-layer change. Confirm the contract in this order: backend, DeepEval, frontend.

## Preserve shared invariants

- Keep authentication, ownership filtering, superuser boundaries, password flows, health checks, and generated OpenAPI workflow intact.
- Make runs reproducible by preserving inputs, expected and actual outputs, evaluator identity, scores, reasons, errors, timestamps, and baseline relationships.
- Derive pass/fail from the configured threshold and keep row- or turn-level evidence visible beside aggregate results.
- Never expose, log, or persist plaintext endpoint headers or API keys.
- Keep outbound evaluation calls POST-only and retain URL validation, SSRF defenses, timeouts, response-size limits, row limits, and concurrency limits.
- Treat unavailable integrations as unavailable capabilities. Never silently replace a selected evaluator with `local`.
- Add a new Alembic revision for persisted schema changes. Never rewrite shipped migration history.
- Never hand-edit `frontend/src/client/*.gen.ts` or `frontend/src/routeTree.gen.ts`.

## Verify proportionally

Run the repository helper from the root for the affected scope:

```bash
.agents/skills/evaluation-hub/scripts/verify_project.sh frontend
.agents/skills/evaluation-hub/scripts/verify_project.sh backend-static
.agents/skills/evaluation-hub/scripts/verify_project.sh async-tests
.agents/skills/evaluation-hub/scripts/verify_project.sh evaluation-tests
.agents/skills/evaluation-hub/scripts/verify_project.sh backend-tests
```

Use `ui` only when the frontend is already running with `npm run dev` on port 5173. Separate implementation failures from missing database, browser, model credentials, or endpoint prerequisites. Never weaken tests to make checks pass.

## Report

Lead with the user-visible or API outcome. List important files, checks, and unresolved prerequisites. Distinguish automated verification from manual visual inspection.
