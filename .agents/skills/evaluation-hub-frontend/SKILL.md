---
name: evaluation-hub-frontend
description: Build, modify, review, debug, or verify EvaluationHub's React 19 evaluation console, including routes, forms, result evidence, regression comparisons, authentication-aware UI, accessibility, responsive layouts, generated OpenAPI client consumption, and Playwright coverage. Use for frontend-only work or the frontend portion of a full-stack EvaluationHub change.
---

# EvaluationHub Frontend

Develop the React evaluation console without drifting from its backend contract or generated-code workflow.

## Load context

1. Read `$evaluation-hub` shared architecture and evaluation-domain references.
2. Read `references/frontend.md` before changing routes, components, navigation, forms, themes, responsive behavior, or Playwright tests.
3. Read `references/framework-sources.md` before relying on framework behavior, library APIs, or external UI inspiration.
4. Load `$evaluation-hub-backend` when the public request or response contract must change.
5. Load `$evaluation-hub-deepeval` when displaying, configuring, or interpreting DeepEval metrics.

## Resolve framework evidence

1. Inspect `frontend/package.json` and the repository-root `bun.lock` before implementation.
2. Identify only the libraries affected by the change and record both their declared ranges and locked versions.
3. Consult each affected library's official documentation, then inspect its official GitHub repository at a tag or release matching the locked version when one exists.
4. Prefer exact-version upstream source and, when present, installed runtime or type declarations over `main` or latest-only examples. Compare the evidence with EvaluationHub's local call sites, shared primitives, configuration, and generated-code boundaries.
5. If official documentation or network access is unavailable, state the limitation, use the lockfile plus any installed package metadata, source, and type declarations, and do not infer current or version-specific behavior.

For React APIs, start with the Korean React reference and fall back to the English `react.dev` source when an API is missing or the translation lags. Use `react-dom/server` only for explicit SSR or static-rendering work; do not introduce server rendering APIs into the current Vite client application.

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

## Use Uiverse selectively

- Treat Uiverse UI Kits as optional visual inspiration, not as an authority over EvaluationHub's shared Radix primitives, Tailwind tokens, or accessibility contracts.
- Open the relevant kit page and the exact child component page at implementation time. Rebuild any useful idea for TypeScript, React 19, Tailwind CSS 4, dark and light themes, 390 px responsiveness, and complete keyboard operation.
- Do not import remote scripts, tracking code, unrelated dependencies, or global styles from Uiverse.
- When materially copying code, recheck that page's current license, preserve the required copyright and MIT notice plus source URL in a nearby comment or repository-approved notice, and report the referenced URLs in the result. Do not rely on a previously observed license state.

## Verify

Run `npm run build` for TypeScript and production bundling. Run focused Playwright files for the changed flow, with their normal backend and fixture prerequisites. Use the shared repository verifier where appropriate. Report the locked versions and official documentation or tagged-source URLs that materially informed the change, including Uiverse URLs when used.

## Example prompt

```text
$evaluation-hub-frontend 단일턴 Live Test의 결과 증거와 오류 상태를 390px 화면에서도 읽기 쉽게 고쳐줘.
```
