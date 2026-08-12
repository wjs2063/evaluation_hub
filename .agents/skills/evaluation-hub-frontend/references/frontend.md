# Frontend conventions

## Use the current stack and locations

- Use React 19, TypeScript, Vite, Tailwind CSS 4, Axios, and the generated OpenAPI client.
- Use TanStack Router, Query, and Table for routing, server state, and tabular evidence.
- Extend Radix-based controls under `frontend/src/components/ui/` instead of creating parallel primitives.
- Add routes under `frontend/src/routes/`; treat `frontend/src/routeTree.gen.ts` as generated.
- Work in `frontend/src/components/Evaluations/` for single-turn, multi-turn, live, regression, and result interfaces.
- Preserve the shared shell under `frontend/src/components/Common/` and `frontend/src/components/Sidebar/`.
- Use tokens in `frontend/src/index.css` and theme state in `frontend/src/components/theme-provider.tsx`.
- Add browser contracts under `frontend/tests/`.

## Preserve information architecture

- Keep Overview at `/`, 업로드 평가 at `/evaluations`, 단일턴 Live/Regression under `/evaluation-single-turn/*`, 멀티턴 Live/Regression under `/evaluation-multi-turn/*`, and the RAG placeholder at `/evaluation-rag`.
- Preserve `/items`, `/admin`, `/settings`, and authentication routes inherited from the template.
- Keep Monitor, Evaluate, Manage, and Administration navigation groups and superuser-only Users visibility.
- Retain API health, appearance, and user controls.

## Present evaluation evidence

- Keep dataset or scenario selection, endpoint configuration, editors, run history, result details, and baseline comparison understandable as one workflow.
- Show evaluator identity and availability before execution.
- Show threshold, aggregate score, pass rate, passed and failed counts, and timestamp after execution.
- Make input, expected output, actual output, metric reason, response status, and error inspectable at row or turn level.
- Preserve score and output deltas in regression comparisons without mutating or hiding the baseline.
- Reuse `EvaluationDetails` for metric evidence where practical.
- Keep long JSON, request bodies, response bodies, and error text readable without breaking the layout.
- Distinguish loading, empty, partial success, unavailable integration, network failure, invalid template, and evaluation failure.
- Never present RAG, Langfuse, or unavailable DeepEval configuration as operational.

## Preserve authentication and contracts

- Preserve authentication headers, auth-aware routing, and Axios error handling until a deliberate client-layer migration is requested.
- Use generated request and response types. Regenerate the client from OpenAPI after a public contract change.
- Never edit `frontend/src/client/*.gen.ts` or `frontend/src/routeTree.gen.ts` directly.
- Preserve accessible names, existing product copy, and `data-testid` contracts used by Playwright.

## Apply the visual system

- Use the compact enterprise-console language already defined in the product.
- Use warm neutral surfaces and orange `primary` tokens for interaction and selection.
- Reserve green, amber, and red for success, warning, and destructive or error meaning.
- Pair every status color with text or an icon.
- Preserve dark, light, and system themes, local persistence, and live system-preference changes.
- Preserve visible keyboard focus and explicit hover, disabled, loading, empty, success, warning, and error states.

## Verify responsive and accessible behavior

- Check approximately 1440 px desktop and 390 px mobile viewports.
- Check off-canvas navigation closure, table overflow, editor width, dialog bounds, sticky headers, and long unbroken error strings.
- Verify keyboard operation, labels, accessible names, status semantics, and contrast in both themes.
- Keep browser assertions focused on user-visible contracts instead of implementation details.

## Run the local workflow

Prefer the host frontend workflow for visual iteration:

```bash
cd frontend
npm run dev -- --host 127.0.0.1
```

Set `frontend/.env` to `VITE_API_URL=http://localhost:8000` when the API runs separately. Do not start or replace the frontend Docker service unless explicitly requested. Run `npm run build` and focused Playwright tests for touched flows; authenticated suites require their normal backend and fixtures.
