# Frontend conventions

## Stack and locations

- React 19, TypeScript, Vite, Tailwind CSS 4
- TanStack Router, Query, and Table
- Radix-based shared controls under `frontend/src/components/ui/`
- Routes under `frontend/src/routes/`; treat `routeTree.gen.ts` as generated
- Evaluation workspaces under `frontend/src/components/Evaluations/`
- Shared shell under `frontend/src/components/Common/` and `frontend/src/components/Sidebar/`
- Global tokens in `frontend/src/index.css`
- Theme state in `frontend/src/components/theme-provider.tsx`
- Playwright tests under `frontend/tests/`

## Current information architecture

- Overview: `/`
- Uploaded evaluation: `/evaluations`
- Single-turn live and regression: `/evaluation-single-turn/*`
- Multi-turn live and regression: `/evaluation-multi-turn/*`
- RAG placeholder: `/evaluation-rag`
- Template foundation: `/items`, `/admin`, `/settings`, and authentication routes

The sidebar groups Monitor, Evaluate, Manage, and Administration. Preserve superuser-only visibility for Users and retain the API health, appearance, and user controls.

## Evaluation UI behavior

- Keep dataset/scenario selection, editors, endpoint configuration, run history, result details, and baseline comparison understandable as one workflow.
- Reuse `EvaluationDetails` for metric evidence where practical.
- Keep large JSON, request bodies, response bodies, and error text readable without breaking the layout.
- Do not present RAG, Langfuse, or unavailable DeepEval configuration as operational.
- Preserve authentication headers and Axios error handling until a deliberate client-layer migration is performed.

## Visual system

- Use the compact enterprise-console language already defined in the project.
- Use warm neutral surfaces and orange `primary` tokens for brand interaction and selection.
- Keep green, amber, and red for success, warning, and destructive/error meaning.
- Use shared semantic tokens and primitives rather than feature-specific accent colors.
- Keep page navigation marks simple and button-like; avoid decorative or visually noisy page logos.
- Preserve dark, light, and system themes, local persistence, and live system preference changes.
- Preserve keyboard focus, hover, disabled, loading, empty, success, warning, and error states.

## Responsive and accessibility checks

- Check approximately 1440 px desktop and 390 px mobile layouts.
- Check off-canvas navigation closure, table overflow, editor widths, dialog bounds, sticky headers, and long error strings.
- Preserve accessible names and `data-testid` contracts used by tests.
- Pair status colors with text or icons and keep contrast readable in both themes.

## Local workflow

Prefer the user's host frontend workflow for visual iteration:

```bash
cd frontend
npm run dev -- --host 127.0.0.1
```

Set `frontend/.env` with `VITE_API_URL=http://localhost:8000` when the API runs separately. Do not start or replace the frontend Docker service unless explicitly requested.

Use `npm run build` for TypeScript and production bundling. Use focused Playwright files for the changed workflow; authenticated suites require their normal backend and fixture prerequisites.
