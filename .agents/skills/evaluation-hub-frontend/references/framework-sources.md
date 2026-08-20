# Official frontend sources

Use this map only for libraries affected by the task. Resolve versions before browsing, prefer primary sources, and do not save static copies of upstream documentation in this repository.

## Resolve the installed version

1. Read `frontend/package.json` for the declared dependency range.
2. Read the repository-root `bun.lock` for the exact resolved package version. Treat the lockfile as authoritative when it differs from the declared range.
3. When dependencies are installed, inspect the resolved package's local `package.json`, runtime source, exported types, and relevant configuration. Do not install or alter dependencies solely to browse source. Use installed type declarations as compatibility evidence, not as proof of runtime behavior.
4. Read the official documentation for the affected API.
5. In the official repository, look for an exact package tag or release matching the lockfile. Confirm the repository's actual tag convention instead of constructing a tag name blindly. If there is no exact tag, use the nearest official release notes and installed source; use `main` only for background and never present it as locked-version behavior.
6. Compare the result with EvaluationHub's local implementation before changing code.

Record the package, locked version, documentation URL, upstream repository URL, selected tag, release, or installed declaration, and any version mismatch that affects the decision. If network access fails, report it and stop at the lockfile plus available local package metadata, source, and declarations rather than guessing what the latest docs say.

## React and React DOM

Start with the Korean official reference:

- [React reference overview](https://ko.react.dev/reference/react)
- [Hooks](https://ko.react.dev/reference/react/hooks)
- [Components](https://ko.react.dev/reference/react/components)
- [APIs](https://ko.react.dev/reference/react/apis)
- [React DOM Server](https://ko.react.dev/reference/react-dom/server)

If the relevant API is absent or the translation trails the installed release, verify it in the corresponding [English React reference](https://react.dev/reference/react). Use [React versions](https://react.dev/versions) to determine the documented major or minor line; React documentation is not published separately for every patch release.

Use these upstream sources for exact implementation evidence:

- [React core source and releases](https://github.com/react/react)
- [React documentation source](https://github.com/reactjs/react.dev)

Prefer the React tag or release matching `bun.lock`, then the installed `react`, `react-dom`, `@types/react`, and `@types/react-dom` package files. Keep runtime source and DefinitelyTyped declarations distinct. Use `react-dom/server` only for requested SSR or static rendering; EvaluationHub's current Vite-rendered client screens must continue to use client APIs.

## Vite and Tailwind CSS

| Library | Official documentation | Official repository | Version check |
| --- | --- | --- | --- |
| Vite | [Vite guide](https://vite.dev/guide/) | [vitejs/vite](https://github.com/vitejs/vite) | Match the locked `vite` release or tag and inspect the installed config types. |
| Tailwind CSS | [Tailwind CSS documentation](https://tailwindcss.com/docs) | [tailwindlabs/tailwindcss](https://github.com/tailwindlabs/tailwindcss) | Match locked `tailwindcss` and `@tailwindcss/vite` versions; verify Tailwind 4 syntax against local CSS and Vite configuration. |

Do not migrate configuration merely because latest documentation shows a newer major. Preserve EvaluationHub's tokens in `frontend/src/index.css` and its existing plugin integration unless the task requires a deliberate migration.

## TanStack

| Library | Official documentation | Official repository | Local comparison |
| --- | --- | --- | --- |
| Router | [TanStack Router](https://tanstack.com/router/latest) | [TanStack/router](https://github.com/TanStack/router) | Inspect route definitions, router plugin configuration, and generated `routeTree.gen.ts` without editing the generated tree. |
| Query | [TanStack Query](https://tanstack.com/query/latest) | [TanStack/query](https://github.com/TanStack/query) | Inspect query keys, cache ownership, mutation invalidation, and error handling. |
| Table | [TanStack Table](https://tanstack.com/table/latest) | [TanStack/table](https://github.com/TanStack/table) | Inspect typed columns, row identity, evidence rendering, and responsive overflow. |

Use only the relevant TanStack product's official documentation and repository. Select a tag or release compatible with the locked package version, because these products use independent version lines.

## Radix Primitives

- Documentation: [Radix Primitives introduction](https://www.radix-ui.com/primitives/docs/overview/introduction), then the affected primitive's page under the same official site.
- Source: [radix-ui/primitives](https://github.com/radix-ui/primitives).

Resolve each affected `@radix-ui/react-*` package independently from `bun.lock`. Confirm package-specific tags or releases and installed types rather than assuming the monorepo has one shared version. Compare documented keyboard behavior, focus management, portal behavior, accessible naming, and controlled state with the wrapper under `frontend/src/components/ui/` before changing it.

## Other installed packages

For a dependency not listed above, inspect its resolved local `package.json` and follow its `homepage` and `repository` fields to discover the official documentation and source repository. Confirm that the destination belongs to the package owner or maintainer. Use registries, search results, blogs, and aggregators only to locate a primary source, never as final API authority.

Apply the same evidence order: locked version, installed files, official documentation, matching official tag or release, then local implementation. Do not silently substitute similarly named community repositories.

## Uiverse UI Kits

Use [Uiverse UI Kits](https://uiverse.io/ui-kits) only when visual exploration materially helps the task. Open both the selected kit URL and the exact component URL dynamically; record both URLs and the access date in working notes.

Before adopting an idea:

1. Reuse EvaluationHub's Radix primitive and tokens whenever they can express the interaction.
2. Reimplement the idea in TypeScript and React 19 with Tailwind CSS 4 rather than pasting framework-agnostic global CSS.
3. Verify dark and light themes, 390 px mobile layout, visible focus, keyboard operation, accessible names, reduced-motion behavior where relevant, and all loading, disabled, error, and success states.
4. Reject remote scripts, analytics or tracking, unnecessary dependencies, unsafe external assets, and global selectors that can escape the component.
5. If code or a substantial style is copied, recheck the kit and component license at that time. Preserve the required copyright and MIT notice and the exact source URL in a nearby source comment or an appropriate repository notice, then include the URLs in the task report. If the license cannot be confirmed, use the page only as non-code visual inspiration.

Uiverse currently labels its UI elements as MIT on the kits page, but treat that statement as time-sensitive and verify it again for every material reuse.
