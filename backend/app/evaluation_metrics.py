import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from app.custom_metrics import ensure_required_values, parse_custom_metric_prompt
from app.models import (
    EvaluationMetricDefinitionCreate,
    EvaluationMetricType,
    EvaluationMode,
)


@dataclass(frozen=True)
class MetricCatalogDefinition:
    display_name: str
    description: str
    required_fields: tuple[str, ...]
    score_direction: str
    uses_llm: bool
    docs_url: str
    evaluation_mode: EvaluationMode = EvaluationMode.SINGLE_TURN
    required_config: tuple[str, ...] = ()
    supports_custom_instruction: bool = False


METRIC_CATALOG: dict[EvaluationMetricType, MetricCatalogDefinition] = {
    EvaluationMetricType.GEVAL_CORRECTNESS: MetricCatalogDefinition(
        "정확성 (G-Eval)",
        "실제 응답이 기대 응답과 사실적·의미적으로 일치하는지 평가합니다.",
        ("actual_output", "expected_output"),
        "higher_is_better",
        True,
        "https://deepeval.com/docs/metrics-llm-evals",
    ),
    EvaluationMetricType.GEVAL_CLARITY: MetricCatalogDefinition(
        "명확성 (G-Eval)",
        "실제 응답이 명확하고 직접적이며 이해하기 쉬운지 평가합니다.",
        ("actual_output",),
        "higher_is_better",
        True,
        "https://deepeval.com/docs/metrics-llm-evals",
    ),
    EvaluationMetricType.GEVAL_PROFESSIONALISM: MetricCatalogDefinition(
        "전문성 (G-Eval)",
        "실제 응답이 전문적이고 존중하는 어조를 유지하는지 평가합니다.",
        ("actual_output",),
        "higher_is_better",
        True,
        "https://deepeval.com/docs/metrics-llm-evals",
    ),
    EvaluationMetricType.ANSWER_RELEVANCY: MetricCatalogDefinition(
        "답변 관련성",
        "실제 응답의 진술이 사용자 입력과 관련되는 비율을 평가합니다.",
        ("input", "actual_output"),
        "higher_is_better",
        True,
        "https://deepeval.com/docs/metrics-answer-relevancy",
    ),
    EvaluationMetricType.SUMMARIZATION: MetricCatalogDefinition(
        "요약 품질",
        "입력을 원문으로 보고 실제 응답의 사실 정합성과 핵심 내용 포함도를 평가합니다.",
        ("input", "actual_output"),
        "higher_is_better",
        True,
        "https://deepeval.com/docs/metrics-summarization",
    ),
    EvaluationMetricType.BIAS: MetricCatalogDefinition(
        "편향 안전성",
        "실제 응답의 성별·정치·인종·지역 편향이 낮을수록 높은 품질 점수로 환산합니다.",
        ("input", "actual_output"),
        "lower_is_better",
        True,
        "https://deepeval.com/docs/metrics-bias",
    ),
    EvaluationMetricType.TOXICITY: MetricCatalogDefinition(
        "유해성 안전성",
        "실제 응답의 공격성·조롱·위협이 낮을수록 높은 품질 점수로 환산합니다.",
        ("input", "actual_output"),
        "lower_is_better",
        True,
        "https://deepeval.com/docs/metrics-toxicity",
    ),
    EvaluationMetricType.PII_LEAKAGE: MetricCatalogDefinition(
        "개인정보 보호",
        "실제 응답에 개인정보나 민감정보 유출이 없는지 평가합니다.",
        ("input", "actual_output"),
        "higher_is_better",
        True,
        "https://deepeval.com/docs/metrics-pii-leakage",
        supports_custom_instruction=True,
    ),
    EvaluationMetricType.EXACT_MATCH: MetricCatalogDefinition(
        "완전 일치",
        "실제 응답과 기대 응답이 문자 단위로 완전히 같은지 결정적으로 평가합니다.",
        ("input", "actual_output", "expected_output"),
        "higher_is_better",
        False,
        "https://deepeval.com/docs/metrics-exact-match",
    ),
    EvaluationMetricType.NON_ADVICE: MetricCatalogDefinition(
        "비전문 조언 안전성",
        "허용되지 않은 전문 조언을 제공하지 않는지 평가합니다.",
        ("input", "actual_output"),
        "higher_is_better",
        True,
        "https://deepeval.com/docs/metrics-non-advice",
        required_config=("advice_types",),
        supports_custom_instruction=True,
    ),
    EvaluationMetricType.MISUSE: MetricCatalogDefinition(
        "도메인 오용",
        "전문 챗봇이 지정 도메인 밖 요청에 응답하는 정도를 평가합니다.",
        ("input", "actual_output"),
        "lower_is_better",
        True,
        "https://deepeval.com/docs/metrics-misuse",
        required_config=("domain",),
        supports_custom_instruction=True,
    ),
    EvaluationMetricType.ROLE_VIOLATION: MetricCatalogDefinition(
        "역할 위반",
        "지정된 역할이나 페르소나를 위반하는지 평가합니다.",
        ("input", "actual_output"),
        "lower_is_better",
        True,
        "https://deepeval.com/docs/metrics-role-violation",
        required_config=("role",),
        supports_custom_instruction=True,
    ),
    EvaluationMetricType.TURN_RELEVANCY: MetricCatalogDefinition(
        "턴 관련성",
        "각 어시스턴트 응답이 이전 대화에 관련되는지 평가합니다.",
        ("turns",),
        "higher_is_better",
        True,
        "https://deepeval.com/docs/metrics-turn-relevancy",
        EvaluationMode.MULTI_TURN,
    ),
    EvaluationMetricType.ROLE_ADHERENCE: MetricCatalogDefinition(
        "역할 준수",
        "전체 대화에서 챗봇 역할을 유지하는지 평가합니다.",
        ("turns", "chatbot_role"),
        "higher_is_better",
        True,
        "https://deepeval.com/docs/metrics-role-adherence",
        EvaluationMode.MULTI_TURN,
        ("chatbot_role",),
    ),
    EvaluationMetricType.KNOWLEDGE_RETENTION: MetricCatalogDefinition(
        "지식 유지",
        "대화 중 도입된 사실을 후속 턴에서 유지하는지 평가합니다.",
        ("turns",),
        "higher_is_better",
        True,
        "https://deepeval.com/docs/metrics-knowledge-retention",
        EvaluationMode.MULTI_TURN,
    ),
    EvaluationMetricType.CONVERSATION_COMPLETENESS: MetricCatalogDefinition(
        "대화 완결성",
        "전체 대화가 사용자 요구를 완결적으로 해결하는지 평가합니다.",
        ("turns",),
        "higher_is_better",
        True,
        "https://deepeval.com/docs/metrics-conversation-completeness",
        EvaluationMode.MULTI_TURN,
    ),
}


class MetricEvaluationResult(BaseModel):
    name: str
    display_name: str
    score: float = Field(ge=0, le=100)
    raw_score_ratio: float | None = Field(default=None, ge=0, le=1)
    score_direction: str
    weight_percent: int = Field(ge=1, le=100)
    weighted_score: float = Field(ge=0, le=100)
    reason: str | None = None
    error: str | None = None


class KoreanReasonBatch(BaseModel):
    reasons: list[str]


def _reason_needs_korean(reason: str | None) -> bool:
    return bool(reason and reason.strip() and not re.search(r"[가-힣]", reason))


def _korean_reason_prompt(reasons: list[str]) -> str:
    payload = json.dumps(reasons, ensure_ascii=False)
    return (
        "Translate each evaluation reason in the JSON array into natural Korean. "
        "Preserve its exact evaluation meaning, facts, metric terminology, and "
        "numbers. Do not add or remove judgments. Return exactly one translated "
        "reason for each input, in the same order, using the structured response "
        f"schema. Input reasons: {payload}"
    )


def _validate_korean_reason_batch(generated: object, expected_count: int) -> list[str]:
    batch = (
        generated
        if isinstance(generated, KoreanReasonBatch)
        else KoreanReasonBatch.model_validate(generated)
    )
    if len(batch.reasons) != expected_count:
        raise ValueError("Korean reason translation count did not match")
    translated = [reason.strip() for reason in batch.reasons]
    if any(not reason or not re.search(r"[가-힣]", reason) for reason in translated):
        raise ValueError("Korean reason translation was not written in Korean")
    return translated


async def _generate_korean_reasons(reasons: list[str], model_name: str) -> list[str]:
    from deepeval.models import GPTModel

    generated, _cost = await GPTModel(model=model_name).a_generate(
        _korean_reason_prompt(reasons), schema=KoreanReasonBatch
    )
    return _validate_korean_reason_batch(generated, len(reasons))


def ensure_korean_reason(reason: str | None, score: float, model_name: str) -> str:
    if reason and not _reason_needs_korean(reason):
        return reason
    if not reason:
        return f"이 지표의 평가 사유가 제공되지 않았습니다. 점수는 {score:.2f}점입니다."
    from deepeval.models import GPTModel

    try:
        generated, _cost = GPTModel(model=model_name).generate(
            _korean_reason_prompt([reason or ""]), schema=KoreanReasonBatch
        )
        return _validate_korean_reason_batch(generated, 1)[0][:2_000]
    except Exception:
        return (
            f"이 지표의 점수는 {score:.2f}점입니다. "
            "상세 평가 사유를 한국어로 생성하지 못했습니다."
        )


async def _localize_metric_reasons(
    results: list[MetricEvaluationResult], model_name: str
) -> None:
    for result in results:
        if not result.reason:
            result.reason = (
                "지표 실행에 실패해 품질 점수를 0점으로 처리했습니다."
                if result.error
                else f"이 지표의 평가 사유가 제공되지 않았습니다. 점수는 {result.score:.2f}점입니다."
            )
    indexes = [
        index
        for index, result in enumerate(results)
        if _reason_needs_korean(result.reason)
    ]
    if not indexes:
        return
    reasons = [results[index].reason or "" for index in indexes]
    try:
        translated = await _generate_korean_reasons(reasons, model_name)
    except Exception:
        translated = [
            (
                f"이 지표의 점수는 {results[index].score:.2f}점입니다. "
                "상세 평가 사유를 한국어로 생성하지 못했습니다."
            )
            for index in indexes
        ]
    for index, reason in zip(indexes, translated, strict=True):
        results[index].reason = reason[:2_000]


def catalog_definition(metric_type: EvaluationMetricType) -> MetricCatalogDefinition:
    return METRIC_CATALOG[metric_type]


def round_score(value: float | Decimal, *, clamp: bool = True) -> float:
    """Round product scores at 3 decimal places using decimal ROUND_HALF_UP."""
    decimal_value = Decimal(str(value)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )
    if clamp:
        decimal_value = min(Decimal("100"), max(Decimal("0"), decimal_value))
    return float(decimal_value)


def quality_score(raw_ratio: float, score_direction: str) -> float:
    ratio = Decimal(str(raw_ratio))
    normalized = Decimal("1") - ratio if score_direction == "lower_is_better" else ratio
    return round_score(normalized * Decimal("100"))


def contribution_score(score: float, weight_percent: int) -> float:
    return round_score(Decimal(str(score)) * Decimal(weight_percent) / Decimal("100"))


def aggregate_score(results: list[MetricEvaluationResult]) -> float:
    unrounded = sum(
        Decimal(str(item.score)) * Decimal(item.weight_percent) / Decimal("100")
        for item in results
    )
    return round_score(unrounded)


def _instruction_template(base: type, instruction: str) -> type:
    """Append bounded prose without replacing DeepEval's variables or JSON schema."""
    text = instruction.strip()[:2000]
    attrs: dict[str, object] = {}
    supported_methods = {
        "NonAdviceTemplate": (
            "generate_advices",
            "generate_reason",
            "generate_verdicts",
        ),
        "MisuseTemplate": ("generate_misuses", "generate_reason", "generate_verdicts"),
        "PIILeakageTemplate": ("extract_pii", "generate_reason", "generate_verdicts"),
        "RoleViolationTemplate": (
            "detect_role_violations",
            "generate_reason",
            "generate_verdicts",
        ),
    }
    methods = supported_methods.get(base.__name__)
    if methods is None:
        raise ValueError("Unsupported DeepEval instruction template")
    for name in methods:
        method = getattr(base, name)

        def wrapped(*args: Any, _method: Any = method, **kwargs: Any) -> str:
            return (
                f"{_method(*args, **kwargs)}\n\nAdditional judge instruction:\n{text}"
            )

        attrs[name] = staticmethod(wrapped)
    return type(f"EvaluationHub{base.__name__}", (base,), attrs)


def _build_metric(
    metric_type: EvaluationMetricType,
    model_name: str,
    config: dict[str, Any] | None = None,
    custom_instruction: str | None = None,
) -> Any:
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        BiasMetric,
        ExactMatchMetric,
        GEval,
        MisuseMetric,
        NonAdviceMetric,
        PIILeakageMetric,
        RoleViolationMetric,
        SummarizationMetric,
        ToxicityMetric,
    )
    from deepeval.test_case import SingleTurnParams

    common: dict[str, Any] = {
        "model": model_name,
        "threshold": None,
        "include_reason": True,
    }
    config = config or {}
    geval_common: dict[str, Any] = {"model": model_name, "threshold": None}
    if metric_type == EvaluationMetricType.GEVAL_CORRECTNESS:
        return GEval(
            name="Correctness",
            criteria=(
                "Determine whether the actual output is factually and semantically "
                "correct according to the expected output. Write the evaluation "
                "reason in natural Korean."
            ),
            evaluation_params=[
                SingleTurnParams.ACTUAL_OUTPUT,
                SingleTurnParams.EXPECTED_OUTPUT,
            ],
            **geval_common,
        )
    if metric_type == EvaluationMetricType.GEVAL_CLARITY:
        return GEval(
            name="Clarity",
            criteria=(
                "Determine whether the actual output is clear, direct, coherent, and "
                "easy for the intended user to understand. Write the evaluation "
                "reason in natural Korean."
            ),
            evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT],
            **geval_common,
        )
    if metric_type == EvaluationMetricType.GEVAL_PROFESSIONALISM:
        return GEval(
            name="Professionalism",
            criteria=(
                "Determine whether the actual output maintains a professional, "
                "respectful, and contextually appropriate tone. Write the evaluation "
                "reason in natural Korean."
            ),
            evaluation_params=[SingleTurnParams.ACTUAL_OUTPUT],
            **geval_common,
        )
    if metric_type == EvaluationMetricType.ANSWER_RELEVANCY:
        return AnswerRelevancyMetric(**common)
    if metric_type == EvaluationMetricType.SUMMARIZATION:
        return SummarizationMetric(**common)
    if metric_type == EvaluationMetricType.BIAS:
        return BiasMetric(**common)
    if metric_type == EvaluationMetricType.TOXICITY:
        return ToxicityMetric(**common)
    if metric_type == EvaluationMetricType.PII_LEAKAGE:
        if custom_instruction:
            from deepeval.metrics.pii_leakage.pii_leakage import PIILeakageTemplate

            common["evaluation_template"] = _instruction_template(
                PIILeakageTemplate, custom_instruction
            )
        return PIILeakageMetric(**common)
    if metric_type == EvaluationMetricType.NON_ADVICE:
        from deepeval.metrics.non_advice.non_advice import NonAdviceTemplate

        if custom_instruction:
            common["evaluation_template"] = _instruction_template(
                NonAdviceTemplate, custom_instruction
            )
        advice_types = config.get("advice_types")
        if not isinstance(advice_types, list) or not all(
            isinstance(item, str) and item.strip() for item in advice_types
        ):
            raise ValueError("non_advice requires non-empty advice_types")
        return NonAdviceMetric(advice_types=cast(list[str], advice_types), **common)
    if metric_type == EvaluationMetricType.MISUSE:
        from deepeval.metrics.misuse.misuse import MisuseTemplate

        if custom_instruction:
            common["evaluation_template"] = _instruction_template(
                MisuseTemplate, custom_instruction
            )
        domain = config.get("domain")
        if not isinstance(domain, str) or not domain.strip():
            raise ValueError("misuse requires a non-empty domain")
        return MisuseMetric(domain=domain, **common)
    if metric_type == EvaluationMetricType.ROLE_VIOLATION:
        from deepeval.metrics.role_violation.role_violation import RoleViolationTemplate

        if custom_instruction:
            common["evaluation_template"] = _instruction_template(
                RoleViolationTemplate, custom_instruction
            )
        role = config.get("role")
        if not isinstance(role, str) or not role.strip():
            raise ValueError("role_violation requires a non-empty role")
        return RoleViolationMetric(role=role, **common)
    if metric_type == EvaluationMetricType.EXACT_MATCH:
        return ExactMatchMetric(threshold=None)
    raise ValueError(f"Unsupported metric type: {metric_type}")


async def evaluate_selected_metrics(
    metrics: list[EvaluationMetricDefinitionCreate],
    *,
    input_text: str,
    actual_output: str,
    expected_output: str,
    model_name: str,
) -> list[MetricEvaluationResult]:
    from deepeval.test_case import LLMTestCase

    test_case = LLMTestCase(
        input=input_text,
        actual_output=actual_output,
        expected_output=expected_output,
    )
    from deepeval.metrics import GEval
    from deepeval.test_case import SingleTurnParams

    param_by_key = {
        "input": SingleTurnParams.INPUT,
        "actual_output": SingleTurnParams.ACTUAL_OUTPUT,
        "expected_output": SingleTurnParams.EXPECTED_OUTPUT,
    }
    instances: list[Any | None] = []
    outcomes: list[object] = []
    for definition in metrics:
        instance: Any | None = None
        try:
            if definition.custom_metric_id is not None:
                if not definition.custom_metric_prompt:
                    raise ValueError("Custom metric prompt snapshot is missing")
                parsed_keys = list(
                    parse_custom_metric_prompt(
                        definition.custom_metric_prompt, "single_turn"
                    )
                )
                if parsed_keys != definition.required_keys:
                    raise ValueError(
                        "Custom metric required_keys snapshot does not match its prompt"
                    )
                ensure_required_values(
                    definition.required_keys,
                    {
                        "input": input_text,
                        "actual_output": actual_output,
                        "expected_output": expected_output,
                    },
                )
                instance = GEval(
                    name=definition.custom_metric_name or "Custom metric",
                    criteria=definition.custom_metric_prompt,
                    evaluation_params=[
                        param_by_key[key] for key in definition.required_keys
                    ],
                    model=model_name,
                    threshold=None,
                )
            else:
                if definition.metric_type is None:
                    raise ValueError("Built-in metric type is missing")
                instance = _build_metric(
                    definition.metric_type,
                    model_name,
                    definition.config,
                    definition.custom_instruction,
                )
            outcome: object = await instance.a_measure(test_case)
        except Exception as exc:
            outcome = exc
        instances.append(instance)
        outcomes.append(outcome)
    results: list[MetricEvaluationResult] = []
    for definition, instance, outcome in zip(metrics, instances, outcomes, strict=True):
        catalog = (
            catalog_definition(definition.metric_type)
            if definition.metric_type is not None
            else None
        )
        name = (
            definition.metric_type.value
            if definition.metric_type is not None
            else f"custom:{definition.custom_metric_id}"
        )
        display_name = (
            catalog.display_name
            if catalog is not None
            else definition.custom_metric_name or "사용자 정의 메트릭"
        )
        score_direction = catalog.score_direction if catalog else "higher_is_better"
        if isinstance(outcome, BaseException):
            results.append(
                MetricEvaluationResult(
                    name=name,
                    display_name=display_name,
                    score=0,
                    raw_score_ratio=None,
                    score_direction=score_direction,
                    weight_percent=definition.weight_percent,
                    weighted_score=0,
                    error=str(outcome)[:1000],
                )
            )
            continue
        if instance is None:
            raise RuntimeError("Metric instance was not constructed")
        raw_score = round(float(instance.score), 6)
        normalized_score = quality_score(raw_score, score_direction)
        reason = getattr(instance, "reason", None)
        if not reason and definition.metric_type == EvaluationMetricType.EXACT_MATCH:
            reason = (
                "실제 응답과 기대 응답이 완전히 일치합니다."
                if raw_score == 1
                else "실제 응답과 기대 응답이 완전히 일치하지 않습니다."
            )
        results.append(
            MetricEvaluationResult(
                name=name,
                display_name=display_name,
                score=normalized_score,
                raw_score_ratio=raw_score,
                score_direction=score_direction,
                weight_percent=definition.weight_percent,
                weighted_score=contribution_score(
                    normalized_score, definition.weight_percent
                ),
                reason=reason,
            )
        )
    await _localize_metric_reasons(results, model_name)
    return results


async def evaluate_conversation_metrics(
    metrics: list[EvaluationMetricDefinitionCreate],
    *,
    turns: list[tuple[str, str]],
    model_name: str,
    expected_outcome: str | None = None,
) -> list[MetricEvaluationResult]:
    from deepeval.metrics import (
        ConversationalGEval,
        ConversationCompletenessMetric,
        KnowledgeRetentionMetric,
        RoleAdherenceMetric,
        TurnRelevancyMetric,
    )
    from deepeval.test_case import ConversationalTestCase, MultiTurnParams, Turn

    definitions = {
        EvaluationMetricType.TURN_RELEVANCY: TurnRelevancyMetric,
        EvaluationMetricType.ROLE_ADHERENCE: RoleAdherenceMetric,
        EvaluationMetricType.KNOWLEDGE_RETENTION: KnowledgeRetentionMetric,
        EvaluationMetricType.CONVERSATION_COMPLETENESS: ConversationCompletenessMetric,
    }
    test_turns = [
        Turn(role=cast(Literal["user", "assistant"], role), content=content)
        for role, content in turns
    ]
    results: list[MetricEvaluationResult] = []
    for definition in metrics:
        if definition.custom_metric_id is not None:
            name = f"custom:{definition.custom_metric_id}"
            display_name = definition.custom_metric_name or "사용자 정의 메트릭"
            try:
                if not definition.custom_metric_prompt:
                    raise ValueError("Custom metric prompt snapshot is missing")
                parsed_keys = list(
                    parse_custom_metric_prompt(
                        definition.custom_metric_prompt, "multi_turn"
                    )
                )
                if parsed_keys != definition.required_keys:
                    raise ValueError(
                        "Custom metric required_keys snapshot does not match its prompt"
                    )
                ensure_required_values(
                    definition.required_keys,
                    {
                        "role": "user, assistant" if test_turns else "",
                        "content": "\n".join(turn.content for turn in test_turns),
                        "expected_outcome": expected_outcome,
                    },
                )
                param_by_key = {
                    "role": MultiTurnParams.ROLE,
                    "content": MultiTurnParams.CONTENT,
                    "expected_outcome": MultiTurnParams.EXPECTED_OUTCOME,
                }
                test_case = ConversationalTestCase(
                    turns=test_turns, expected_outcome=expected_outcome
                )
                metric = ConversationalGEval(
                    name=display_name,
                    criteria=definition.custom_metric_prompt,
                    evaluation_params=[
                        param_by_key[key] for key in definition.required_keys
                    ],
                    model=model_name,
                    threshold=None,
                )
                await metric.a_measure(test_case)
                raw_ratio = round(float(metric.score or 0), 6)
                score = quality_score(raw_ratio, "higher_is_better")
                results.append(
                    MetricEvaluationResult(
                        name=name,
                        display_name=display_name,
                        score=score,
                        raw_score_ratio=raw_ratio,
                        score_direction="higher_is_better",
                        weight_percent=definition.weight_percent,
                        weighted_score=contribution_score(
                            score, definition.weight_percent
                        ),
                        reason=getattr(metric, "reason", None),
                    )
                )
            except Exception as exc:
                results.append(
                    MetricEvaluationResult(
                        name=name,
                        display_name=display_name,
                        score=0,
                        raw_score_ratio=None,
                        score_direction="higher_is_better",
                        weight_percent=definition.weight_percent,
                        weighted_score=0,
                        error=str(exc)[:1000],
                    )
                )
            continue
        if definition.metric_type is None:
            raise ValueError("Built-in metric type is missing")
        metric_class = definitions.get(definition.metric_type)
        if metric_class is None:
            raise ValueError(
                "single-turn metric cannot be used for a multi-turn evaluation"
            )
        test_case = ConversationalTestCase(
            turns=test_turns,
            chatbot_role=definition.config.get("chatbot_role"),
        )
        metric = metric_class(model=model_name, threshold=None, include_reason=True)
        catalog = catalog_definition(definition.metric_type)
        try:
            await metric.a_measure(test_case)
            raw_ratio = round(float(metric.score or 0), 6)
            score = quality_score(raw_ratio, catalog.score_direction)
            results.append(
                MetricEvaluationResult(
                    name=definition.metric_type.value,
                    display_name=catalog.display_name,
                    score=score,
                    raw_score_ratio=raw_ratio,
                    score_direction=catalog.score_direction,
                    weight_percent=definition.weight_percent,
                    weighted_score=contribution_score(score, definition.weight_percent),
                    reason=getattr(metric, "reason", None),
                )
            )
        except Exception as exc:
            results.append(
                MetricEvaluationResult(
                    name=definition.metric_type.value,
                    display_name=catalog.display_name,
                    score=0,
                    raw_score_ratio=None,
                    score_direction=catalog.score_direction,
                    weight_percent=definition.weight_percent,
                    weighted_score=0,
                    error=str(exc)[:1000],
                )
            )
    await _localize_metric_reasons(results, model_name)
    return results
