# EvaluationHub DeepEval integration

## Reconfirm the compatibility boundary

- Read `backend/pyproject.toml` and `uv.lock` before changing DeepEval code.
- Treat the current range `deepeval>=4.1.3,<5.0.0` and locked 4.1.5 API as the present baseline, not a permanent signature guarantee.
- Open the official metric document and introspect the installed class constructor, test-case constructor, and `a_measure` immediately before implementation.
- Run all inspection and tests through `uv run`.

## Use EvaluationHub configuration

- Pass `settings.DEEPEVAL_MODEL`, currently sourced from `DEEPEVAL_MODEL`, to every DeepEval judge metric.
- Read OpenAI credentials through the existing settings and environment boundary.
- Never log or return model credentials.
- Treat a missing package or credential as an unavailable integration with an actionable error.
- Never run `local` automatically after DeepEval setup or execution fails.

## Keep async execution non-blocking

- Prefer the installed metric's supported `a_measure` method from async application paths.
- Await `a_measure` directly and preserve cancellation and exception behavior.
- Use a bounded worker thread only for a metric or SDK path that has no compatible async method.
- Do not hold an `AsyncSession` transaction open while the judge runs.
- Apply existing concurrency and timeout boundaries to judge execution.

The locked DeepEval 4.1.5 classes documented by this skill expose `a_measure`, including all eleven built-in multi-turn metrics, `GEval`, `DAGMetric`, `ConversationalGEval`, `ConversationalDAGMetric`, and `ArenaGEval`. Reconfirm this after every dependency change.

## Preserve metric-specific outcomes

- Preserve metric name, numeric score where the metric defines one, reason, and error independently.
- Preserve `ArenaGEval` winner and reason as comparison output; do not coerce the winner into a numeric score.
- Preserve partial metric failures instead of hiding them behind an aggregate.
- Derive pass/fail only for metrics whose contract has a threshold and numeric score.
- Never average heterogeneous metric scores without an explicit, versioned product rule.

## Respect the current schema

EvaluationHub currently uses `geval_score` and `geval_reason` for one conversational G-Eval result. Do not pack several metric results into those columns, concatenate reasons, overwrite one metric with another, or create a synthetic average.

When implementing real multi-metric evaluation, update one vertical slice:

1. Define a metric configuration and result API contract.
2. Add normalized metric-result persistence and a new Alembic revision.
3. Preserve metric-level score or winner, reason, error, threshold, and identity.
4. Regenerate OpenAPI and the frontend client.
5. Add frontend configuration and evidence-rich result presentation.
6. Add backend, migration, generated-client, and Playwright coverage.

Load `$evaluation-hub-backend` for steps 1-4 and `$evaluation-hub-frontend` for steps 4-6.
