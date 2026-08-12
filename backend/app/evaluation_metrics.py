import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from app.models import EvaluationMetricDefinitionCreate, EvaluationMetricType


@dataclass(frozen=True)
class MetricCatalogDefinition:
    display_name: str
    description: str
    required_fields: tuple[str, ...]
    score_direction: str
    uses_llm: bool
    docs_url: str


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
    ),
    EvaluationMetricType.EXACT_MATCH: MetricCatalogDefinition(
        "완전 일치",
        "실제 응답과 기대 응답이 문자 단위로 완전히 같은지 결정적으로 평가합니다.",
        ("input", "actual_output", "expected_output"),
        "higher_is_better",
        False,
        "https://deepeval.com/docs/metrics-exact-match",
    ),
}


class MetricEvaluationResult(BaseModel):
    name: str
    display_name: str
    score: float = Field(ge=0, le=1)
    raw_score: float | None = Field(default=None, ge=0, le=1)
    score_direction: str
    weight_percent: int = Field(ge=1, le=100)
    weighted_score: float = Field(ge=0, le=1)
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


def ensure_korean_reason(
    reason: str | None, score: float, model_name: str
) -> str | None:
    if not _reason_needs_korean(reason):
        return reason
    from deepeval.models import GPTModel

    try:
        generated, _cost = GPTModel(model=model_name).generate(
            _korean_reason_prompt([reason]), schema=KoreanReasonBatch
        )
        return _validate_korean_reason_batch(generated, 1)[0][:2_000]
    except Exception:
        return (
            f"이 지표의 점수는 {score * 100:.2f}점입니다. "
            "상세 평가 사유를 한국어로 생성하지 못했습니다."
        )


async def _localize_metric_reasons(
    results: list[MetricEvaluationResult], model_name: str
) -> None:
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
                f"이 지표의 점수는 {results[index].score * 100:.2f}점입니다. "
                "상세 평가 사유를 한국어로 생성하지 못했습니다."
            )
            for index in indexes
        ]
    for index, reason in zip(indexes, translated, strict=True):
        results[index].reason = reason[:2_000]


def catalog_definition(metric_type: EvaluationMetricType) -> MetricCatalogDefinition:
    return METRIC_CATALOG[metric_type]


def _build_metric(metric_type: EvaluationMetricType, model_name: str) -> Any:
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        BiasMetric,
        ExactMatchMetric,
        GEval,
        PIILeakageMetric,
        SummarizationMetric,
        ToxicityMetric,
    )
    from deepeval.test_case import SingleTurnParams

    common = {"model": model_name, "threshold": None, "include_reason": True}
    geval_common = {"model": model_name, "threshold": None}
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
        return PIILeakageMetric(**common)
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
    instances = [
        _build_metric(definition.metric_type, model_name) for definition in metrics
    ]
    outcomes: list[object] = []
    for instance in instances:
        try:
            outcomes.append(await instance.a_measure(test_case))
        except Exception as exc:
            outcomes.append(exc)
    results: list[MetricEvaluationResult] = []
    for definition, instance, outcome in zip(metrics, instances, outcomes, strict=True):
        catalog = catalog_definition(definition.metric_type)
        if isinstance(outcome, BaseException):
            results.append(
                MetricEvaluationResult(
                    name=definition.metric_type.value,
                    display_name=catalog.display_name,
                    score=0,
                    raw_score=None,
                    score_direction=catalog.score_direction,
                    weight_percent=definition.weight_percent,
                    weighted_score=0,
                    error=str(outcome)[:1000],
                )
            )
            continue
        raw_score = round(float(instance.score), 4)
        quality_score = (
            round(1 - raw_score, 4)
            if catalog.score_direction == "lower_is_better"
            else raw_score
        )
        reason = getattr(instance, "reason", None)
        if not reason and definition.metric_type == EvaluationMetricType.EXACT_MATCH:
            reason = (
                "실제 응답과 기대 응답이 완전히 일치합니다."
                if raw_score == 1
                else "실제 응답과 기대 응답이 완전히 일치하지 않습니다."
            )
        results.append(
            MetricEvaluationResult(
                name=definition.metric_type.value,
                display_name=catalog.display_name,
                score=quality_score,
                raw_score=raw_score,
                score_direction=catalog.score_direction,
                weight_percent=definition.weight_percent,
                weighted_score=round(
                    quality_score * definition.weight_percent / 100, 4
                ),
                reason=reason,
            )
        )
    await _localize_metric_reasons(results, model_name)
    return results
