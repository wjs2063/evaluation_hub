# DeepEval custom metrics

Read the affected official document and inspect the installed constructor before implementation.

| Evaluation need | Official document | Class | Test case | Required inputs and mapping |
| --- | --- | --- | --- | --- |
| Subjective single-turn judgment | [G-Eval](https://deepeval.com/docs/metrics-llm-evals) | `GEval` | `LLMTestCase` | Provide test-case `input` and `actual_output`; add `expected_output`, `context`, `retrieval_context`, or `tools_called` only when referenced by `SingleTurnParams` and the rubric. Construct with `name`, matching `evaluation_params`, and exactly one of `criteria` or `evaluation_steps`. |
| Rule-shaped single-turn scoring | [DAG](https://deepeval.com/docs/metrics-dag) | `DAGMetric` | `LLMTestCase` | Provide at least test-case `input` plus every field read by graph nodes, commonly `actual_output`, `expected_output`, or `tools_called`. Construct with `name` and `DeepAcyclicGraph`. |
| Subjective whole-conversation judgment | [Conversational G-Eval](https://deepeval.com/docs/metrics-conversational-g-eval) | `ConversationalGEval` | `ConversationalTestCase` | Provide `turns`; map `retrieval_context` and `tools_called` onto turns when used. Construct with `name`, matching `MultiTurnParams`, and exactly one of `criteria` or `evaluation_steps`. |
| Rule-shaped conversational scoring | [Conversational DAG](https://deepeval.com/docs/metrics-conversational-dag) | `ConversationalDAGMetric` | `ConversationalTestCase` | Provide `turns` and every turn field read by conversational graph nodes. Construct with `name` and `DeepAcyclicGraph`. |
| Relative candidate comparison | [Arena G-Eval](https://deepeval.com/docs/metrics-arena-g-eval) | `ArenaGEval` | `ArenaTestCase` | Provide `contestants`; give each contestant an `LLMTestCase` with every field named by `SingleTurnParams`. Construct with `name`, `evaluation_params`, and exactly one of `criteria` or `evaluation_steps`. Preserve `winner` and `reason`. |

## Choose the metric intentionally

- Choose `GEval` when the rubric is holistic and subjective for one input and output.
- Choose `DAGMetric` when the rubric has gates, conditional branches, or explicitly controlled terminal scores.
- Choose `ConversationalGEval` when the criterion judges quality across the complete ordered conversation.
- Choose `ConversationalDAGMetric` when conversational rules require a decision tree or controlled branch scores.
- Choose `ArenaGEval` when the product question is which candidate is better.

Do not convert `ArenaGEval.winner` and `ArenaGEval.reason` into an arbitrary 0-1 score. Introduce an explicit comparison-result API and persistence contract if EvaluationHub adds arena evaluation.

## Keep rubric fields honest

- Include only evaluation parameters mentioned in `criteria` or `evaluation_steps`.
- Provide every test-case field referenced by those parameters.
- Preserve `retrieval_context`, `expected_output`, `tools_called`, and conversation metadata as structured evidence.
- Never reuse `LLMTestCase` for a whole-conversation metric or `ConversationalTestCase` for a single-turn metric.
