# DeepEval 4.1.8 safety metrics

Verify these constructors and `a_measure` against the installed 4.1.8 package before editing integration code.

| Metric | Constructor configuration | Direction used by EvaluationHub | Mode | Custom template | Official reference |
| --- | --- | --- | --- | --- | --- |
| Bias | none | lower is safer | single-turn | no product instruction injection; translate the resulting reason | https://deepeval.com/docs/metrics-bias |
| Toxicity | none | lower is safer | single-turn | no product instruction injection; translate the resulting reason | https://deepeval.com/docs/metrics-toxicity |
| Non-Advice | non-empty `advice_types: list[str]` | higher is safer | single-turn | `evaluation_template` | https://deepeval.com/docs/metrics-non-advice |
| Misuse | non-empty `domain: str` | **lower is safer in the locked 4.1.8 implementation** | single-turn | `evaluation_template` | https://deepeval.com/docs/metrics-misuse |
| PII Leakage | none | higher is safer | single-turn | `evaluation_template` | https://deepeval.com/docs/metrics-pii-leakage |
| Role Violation | non-empty `role: str` | lower is safer | single-turn | `evaluation_template` | https://deepeval.com/docs/metrics-role-violation |

All six require `LLMTestCase.input` and `actual_output`. The product stores DeepEval's original value as `raw_score_ratio` (0-1) and exposes normalized quality as 0-100.

## Safe additional instructions

For Non-Advice, Misuse, PII Leakage, and Role Violation, subclass the installed default template and append at most 2,000 characters of plain judge guidance to every generated prompt. Preserve the original variables, extraction stages, and JSON schemas. Never accept Python, imports, callable names, arbitrary template code, or a replacement system message.

Bias and Toxicity do not use product instructions. Run their normal measurement and translate a non-Korean reason with the configured judge. Every reason path is: request Korean in the judge criteria when supported, validate the returned text contains Korean, then use a fixed Korean fallback on translation failure.

## Misuse regression boundary

DeepEval 4.1.8 `_calculate_score` counts `yes` misuse verdicts and returns `misuse_count / verdict_count`, despite the current prose documentation describing the opposite direction. EvaluationHub therefore treats the locked raw score as lower-is-safer and must retain a regression test for this behavior.
