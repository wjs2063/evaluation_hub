# AI evaluation domain

## Current evaluation modes

| Mode | Stored definition | Execution | Primary evidence |
| --- | --- | --- | --- |
| Single-turn live | Dataset and rows | Call a managed endpoint per row | Input, expected/actual output, metrics, response, error |
| Single-turn regression | Dataset plus saved runs | Re-run and optionally compare a baseline run | Output change, score delta, pass/fail |
| Multi-turn live | Scenario and ordered turns | Execute turns against one managed endpoint | Per-turn request/output/score plus conversation score |
| Multi-turn regression | Scenario plus saved runs | Re-run and optionally compare a baseline | Per-turn output changes and overall comparison |
| Upload evaluation | CSV or JSON payload | Evaluate supplied actual outputs | Aggregate score and row-level local metrics |
| RAG | Placeholder route | Not implemented | Do not imply production support |

## Core entities

- `EvaluationEndpoint`: admin-managed base URL, active state, and encrypted headers. Public responses expose only `headers_configured`.
- `EvaluationDataset`: owner-scoped single-turn configuration, endpoint, request template, response path, threshold, evaluator, and rows.
- `EvaluationDatasetRow`: input and expected output.
- `EvaluationRun` and `EvaluationRunRow`: immutable execution snapshot, aggregate values, row evidence, and optional baseline relationship.
- `EvaluationScenario`: owner-scoped multi-turn configuration tied to a managed endpoint.
- `EvaluationScenarioTurn`: ordered request definition with identifier, relative URL, body template, response extraction path, expected output, and encrypted headers.
- `EvaluationScenarioRun` and `EvaluationScenarioRunTurn`: conversation aggregate, per-turn evidence, error state, and optional baseline relationship.

## Evaluators

- `local`: deterministic exact match, string similarity, and token recall; available without credentials.
- `deepeval`: GEval-style natural-language judging; require the installed DeepEval package and `OPENAI_API_KEY`. Use `DEEPEVAL_MODEL` from settings.
- `langfuse`: advertised as unavailable until credentials and adapter behavior are implemented.

Do not silently fall back from a selected external evaluator to `local`; that changes evaluation meaning. Return an actionable unavailable/error state.

## Scoring rules

- Normalize product quality scores and thresholds to 0–100. Keep raw evaluator ratios at 0–1 only as audit evidence.
- Calculate each metric contribution as `quality_score * weight_percent / 100`, sum unrounded contributions, and apply decimal `ROUND_HALF_UP` at three places.
- Derive row or turn pass/fail from `score >= threshold`.
- Preserve metric name, quality score, raw ratio, weight, contribution, Korean reason, and error where available.
- New multi-turn runs use the selected profile's supported metric weights totaling exactly 100. Do not use the legacy turn-average 40% plus conversational score 60% blend.
- Pass rate and Arena win rate remain ratios; they are not quality scores.
- Compare baselines without mutating the baseline run. Mark missing baseline rows or turns explicitly.
- Keep aggregate counts consistent: `total = passed + failed` for completed evidence.

## Dataset contracts

- Upload CSV or JSON at no more than 5 MB for the direct evaluation endpoint.
- Require `input`, `actual_output`, and `expected_output` for direct uploaded evaluation.
- Accept an array of JSON objects or `{ "data": [...] }` where supported.
- Stored dataset imports use input and expected output; actual output is produced by endpoint execution.
- Keep server-side execution caps authoritative: page size 200, execution rows 1,000, saved dataset bytes 100 MB, and external response bytes 1 MB unless intentionally redesigned.

## Result UX

- Show evaluator identity and availability before execution.
- Show threshold, aggregate score, pass rate, passed/failed counts, and timestamp.
- Make row/turn input, expected output, actual output, reason, response status, and error inspectable.
- Pair semantic colors with text or icons. Do not communicate pass/fail or availability by color alone.
- Keep loading, empty, partial success, unavailable integration, network failure, invalid template, and evaluation failure visually distinct.
