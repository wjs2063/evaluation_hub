---
name: evaluation-hub-deepeval
description: Select, map, integrate, review, debug, or verify DeepEval metrics in EvaluationHub, including multi-turn metrics, custom G-Eval and DAG evaluators, test-case field mapping, async judge execution, model configuration, result preservation, and multi-metric contract design. Use whenever EvaluationHub code imports, configures, executes, stores, or displays DeepEval behavior.
---

# EvaluationHub DeepEval

Select and integrate DeepEval metrics without changing evaluation meaning or forcing incompatible results into the current contract.

## Reconfirm before changing code

1. Inspect `backend/pyproject.toml`, `uv.lock`, and the installed DeepEval version.
2. Read the official document linked for every affected metric.
3. Introspect the installed metric constructor, test-case constructor, and `a_measure` support.
4. Read `references/multi-turn-metrics.md` for built-in conversational metrics.
5. Read `references/custom-metrics.md` for `GEval`, DAG, conversational custom metrics, or arena comparisons.
6. Read `references/evaluationhub-integration.md` before changing EvaluationHub execution, persistence, API, or UI behavior.

Do not rely on remembered signatures. The repository currently pins `deepeval>=4.1.3,<5.0.0` and locks 4.1.5, while official documentation can move within 4.1.x.

## Select by evaluation meaning

- Use `GEval` for subjective single-turn judgment.
- Use `DAGMetric` for rule-shaped single-turn gates and controlled score branches.
- Use `ConversationalGEval` for subjective judgment across an entire conversation.
- Use `ConversationalDAGMetric` for rule-shaped multi-turn decision trees.
- Use `ArenaGEval` to compare candidates. Preserve its winner and reason; never invent a 0-1 score conversion.
- Use a built-in multi-turn metric when its documented meaning and required evidence match the product requirement.

## Preserve execution and results

- Pass `settings.DEEPEVAL_MODEL`; never accept a drifting library default as EvaluationHub's judge model.
- Prefer `await metric.a_measure(test_case)` in async paths when the installed metric supports it.
- Isolate only incompatible synchronous evaluator calls in a worker thread.
- Preserve metric-specific name, score or winner, reason, and error.
- Never silently fall back to `local` when DeepEval is unavailable or fails.
- Never collapse multiple metrics into one synthetic score unless an explicit product contract defines the aggregation.
- Do not force real multi-metric output into the current `geval_score` and `geval_reason` columns. Add explicit API, persistence, migration, generated-client, and UI contracts for a multi-metric feature.

## Coordinate cross-layer changes

Load `$evaluation-hub-backend` for execution, schema, persistence, secrets, or API changes. Load `$evaluation-hub-frontend` for configuration or result presentation. For a full-stack change, confirm backend, DeepEval, then frontend contracts.

## Example prompt

```text
$evaluation-hub-deepeval 멀티턴 상담 품질에 맞는 지표를 고르고 필요한 Turn 필드와 결과 저장 계약을 설계해줘.
```
