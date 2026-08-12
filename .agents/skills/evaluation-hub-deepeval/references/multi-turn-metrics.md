# DeepEval multi-turn metrics

Use these official 4.1.x documents as the authority, then verify the installed API before editing code.

| Meaning | Official document | Class | Test case | Required evidence and mapping |
| --- | --- | --- | --- | --- |
| Keep assistant replies relevant to prior turns | [Turn Relevancy](https://deepeval.com/docs/metrics-turn-relevancy) | `TurnRelevancyMetric` | `ConversationalTestCase` | Set `turns`; give every scored `Turn` a `role` and `content`. |
| Maintain the intended persona or role | [Role Adherence](https://deepeval.com/docs/metrics-role-adherence) | `RoleAdherenceMetric` | `ConversationalTestCase` | Set `turns` and top-level `chatbot_role`; give turns `role` and `content`. |
| Retain facts introduced during a conversation | [Knowledge Retention](https://deepeval.com/docs/metrics-knowledge-retention) | `KnowledgeRetentionMetric` | `ConversationalTestCase` | Set `turns`; give turns `role` and `content`. |
| Satisfy user needs across an end-to-end exchange | [Conversation Completeness](https://deepeval.com/docs/metrics-conversation-completeness) | `ConversationCompletenessMetric` | `ConversationalTestCase` | Set `turns`; give turns `role` and `content`. |
| Plan and execute toward a goal | [Goal Accuracy](https://deepeval.com/docs/metrics-goal-accuracy) | `GoalAccuracyMetric` | `ConversationalTestCase` | Set `turns`; map agent tool actions to `Turn.tools_called` when present. |
| Select tools and generate appropriate arguments | [Tool Use](https://deepeval.com/docs/metrics-tool-use) | `ToolUseMetric` | `ConversationalTestCase` | Set `turns`; map actual actions to `Turn.tools_called`; pass all available tool definitions as the metric constructor's required `available_tools`. |
| Stay inside allowed topics | [Topic Adherence](https://deepeval.com/docs/metrics-topic-adherence) | `TopicAdherenceMetric` | `ConversationalTestCase` | Set `turns`; pass allowed topic strings as the metric constructor's required `relevant_topics`. |
| Ground assistant claims in retrieved evidence | [Turn Faithfulness](https://deepeval.com/docs/metrics-turn-faithfulness) | `TurnFaithfulnessMetric` | `ConversationalTestCase` | Set `turns`; map retrieved evidence to each applicable `Turn.retrieval_context`. |
| Rank relevant retrieved nodes above irrelevant nodes | [Turn Contextual Precision](https://deepeval.com/docs/metrics-turn-contextual-precision) | `TurnContextualPrecisionMetric` | `ConversationalTestCase` | Set `turns` and top-level `expected_outcome`; map ranked evidence to each applicable `Turn.retrieval_context`. |
| Retrieve enough evidence for the expected outcome | [Turn Contextual Recall](https://deepeval.com/docs/metrics-turn-contextual-recall) | `TurnContextualRecallMetric` | `ConversationalTestCase` | Set `turns` and top-level `expected_outcome`; map evidence to each applicable `Turn.retrieval_context`. |
| Retrieve evidence relevant to each user request | [Turn Contextual Relevancy](https://deepeval.com/docs/metrics-turn-contextual-relevancy) | `TurnContextualRelevancyMetric` | `ConversationalTestCase` | Set `turns`; map evidence to each applicable `Turn.retrieval_context`. |

## Map fields deliberately

- Map EvaluationHub ordered messages to `ConversationalTestCase.turns` without discarding role or content.
- Put `expected_outcome` and `chatbot_role` on `ConversationalTestCase`, not on individual turns.
- Put `retrieval_context` and `tools_called` on the applicable `Turn` objects.
- Pass `available_tools` to `ToolUseMetric` and `relevant_topics` to `TopicAdherenceMetric`; do not invent test-case fields with those names.
- Preserve tool names and arguments in `ToolCall` objects. Do not flatten them into prose.
- Reject a metric configuration when required evidence is absent. Do not manufacture empty contexts, roles, outcomes, tools, or topics to make construction succeed.
