---
name: evaluation-hub-frontend
description: Build, modify, review, debug, or verify EvaluationHub's React 19 evaluation console, including routes, forms, result evidence, regression comparisons, authentication-aware UI, accessibility, responsive layouts, generated OpenAPI client consumption, and Playwright coverage. Use for frontend-only work or the frontend portion of a full-stack EvaluationHub change.
---

# EvaluationHub Frontend

Develop the React evaluation console without drifting from its backend contract or generated-code workflow.

## Load context

1. Read `$evaluation-hub` shared architecture and evaluation-domain references.
2. Read `references/frontend.md` before changing routes, components, navigation, forms, themes, responsive behavior, or Playwright tests.
3. Load `$evaluation-hub-backend` when the public request or response contract must change.
4. Load `$evaluation-hub-deepeval` when displaying, configuring, or interpreting DeepEval metrics.

## Work from evidence to UX

1. Trace the route, query or mutation, generated client type, shared primitive, and focused Playwright contract.
2. Preserve authentication state, ownership boundaries, accessible names, product copy, and `data-testid` values unless the request explicitly changes them.
3. Keep configuration, evaluator availability, threshold meaning, row or turn evidence, errors, and baseline deltas inspectable.
4. Reuse shared primitives and design tokens before adding route-specific components or colors.
5. Verify approximately 1440 px desktop and 390 px mobile layouts.

## Protect generated sources

- Consume Axios and the generated OpenAPI client under `frontend/src/client/`.
- Regenerate the client after a public OpenAPI change; never hand-edit `frontend/src/client/*.gen.ts`.
- Let TanStack Router regenerate `frontend/src/routeTree.gen.ts`; never edit it directly.
- Preserve TanStack Query cache and invalidation behavior across mutations.

## Verify

Run `npm run build` for TypeScript and production bundling. Run focused Playwright files for the changed flow, with their normal backend and fixture prerequisites. Use the shared repository verifier where appropriate.

## Example prompt

```text
$evaluation-hub-frontend 단일턴 Live Test의 결과 증거와 오류 상태를 390px 화면에서도 읽기 쉽게 고쳐줘.
```
