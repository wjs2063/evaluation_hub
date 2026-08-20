import asyncio
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.custom_metrics import CustomMetricPlaceholderError, parse_custom_metric_prompt
from app.evaluation_metrics import (
    METRIC_CATALOG,
    MetricEvaluationResult,
    aggregate_score,
    contribution_score,
    evaluate_conversation_metrics,
    evaluate_selected_metrics,
    quality_score,
    round_score,
)
from app.models import (
    CustomMetricCreate,
    EvaluationMetricDefinitionCreate,
    EvaluationMetricProfileCreate,
    EvaluationMetricType,
    EvaluationMode,
    EvaluationScope,
)


@pytest.mark.parametrize(
    ("scope", "prompt", "expected"),
    [
        (
            "quick_upload",
            "{{input}} {{actual_output}} {{expected_output}} {{input}}",
            ("input", "actual_output", "expected_output"),
        ),
        (
            "single_turn",
            "{{expected_output}} {{input}} {{actual_output}}",
            ("expected_output", "input", "actual_output"),
        ),
        (
            "multi_turn",
            "{{role}} {{content}} {{expected_outcome}} {{content}}",
            ("role", "content", "expected_outcome"),
        ),
        ("single_turn", "일반 문장의 {input} 중괄호와 {{input}}", ("input",)),
    ],
)
def test_custom_metric_placeholders_preserve_supported_keys_in_source_order(
    scope: str, prompt: str, expected: tuple[str, ...]
) -> None:
    assert parse_custom_metric_prompt(prompt, scope) == expected


@pytest.mark.parametrize(
    "prompt",
    [
        "{{ input }} 평가",
        "{{Input}} 평가",
        "{{input.value}} 평가",
        "{{input-name}} 평가",
        "{{}} 평가",
        "{{{{input}}}} 평가",
        "{{input} 평가",
        "{{input 평가",
        "닫힘 }} 만 있는 평가",
    ],
)
def test_custom_metric_rejects_every_malformed_reserved_placeholder(
    prompt: str,
) -> None:
    with pytest.raises(CustomMetricPlaceholderError) as error:
        parse_custom_metric_prompt(prompt, "single_turn")
    assert error.value.error_type == "custom_metric_placeholder_malformed"
    assert error.value.invalid_tokens


def test_custom_metric_reports_all_cross_scope_and_unsupported_keys() -> None:
    with pytest.raises(CustomMetricPlaceholderError) as error:
        parse_custom_metric_prompt(
            "{{role}} {{content}} {{some_key}} {{role}}", "single_turn"
        )
    assert error.value.error_type == "custom_metric_placeholder_not_allowed"
    assert error.value.invalid_tokens == ("role", "content", "some_key")
    assert error.value.allowed_keys == (
        "input",
        "actual_output",
        "expected_output",
    )


def test_custom_metric_requires_a_reserved_placeholder() -> None:
    with pytest.raises(CustomMetricPlaceholderError) as error:
        parse_custom_metric_prompt("일반 문장의 {input}만 있습니다.", "single_turn")
    assert error.value.error_type == "custom_metric_placeholder_required"


@pytest.mark.parametrize(
    ("prompt", "error_type"),
    [
        (
            "placeholder가 없는 충분히 긴 평가 기준입니다.",
            "custom_metric_placeholder_required",
        ),
        (
            "{{ input }} 문법이 잘못된 평가 기준입니다.",
            "custom_metric_placeholder_malformed",
        ),
        (
            "{{role}} {{content}} 범위가 잘못된 평가 기준입니다.",
            "custom_metric_placeholder_not_allowed",
        ),
    ],
)
def test_custom_metric_prompt_pydantic_errors_are_typed_and_located_on_prompt(
    prompt: str, error_type: str
) -> None:
    with pytest.raises(ValidationError) as error:
        CustomMetricCreate(
            name="검증 메트릭",
            evaluation_scope=EvaluationScope.SINGLE_TURN,
            prompt=prompt,
        )
    detail = error.value.errors(include_url=False)[0]
    assert detail["type"] == error_type
    assert detail["loc"] == ("prompt",)
    assert detail["ctx"]["evaluation_scope"] == "single_turn"
    assert detail["ctx"]["allowed_keys"] == [
        "input",
        "actual_output",
        "expected_output",
    ]


def test_custom_metric_prompt_accepts_maximum_length_and_rejects_one_more() -> None:
    prefix = "{{input}}"
    CustomMetricCreate(
        name="최대 길이",
        evaluation_scope=EvaluationScope.SINGLE_TURN,
        prompt=prefix + "가" * (8000 - len(prefix)),
    )
    with pytest.raises(ValidationError) as error:
        CustomMetricCreate(
            name="최대 길이 초과",
            evaluation_scope=EvaluationScope.SINGLE_TURN,
            prompt=prefix + "가" * (8001 - len(prefix)),
        )
    assert error.value.errors(include_url=False)[0]["type"] == "string_too_long"


def test_profile_supports_exactly_one_custom_metric_identity() -> None:
    custom_id = uuid.uuid4()
    profile = EvaluationMetricProfileCreate(
        name="빠른 업로드 Custom",
        evaluation_scope=EvaluationScope.QUICK_UPLOAD,
        metrics=[
            EvaluationMetricDefinitionCreate(
                custom_metric_id=custom_id, weight_percent=100
            )
        ],
    )
    assert profile.evaluation_mode == EvaluationMode.SINGLE_TURN
    with pytest.raises(ValidationError, match="exactly one"):
        EvaluationMetricDefinitionCreate(weight_percent=100)
    with pytest.raises(ValidationError, match="exactly one"):
        EvaluationMetricDefinitionCreate(
            metric_type=EvaluationMetricType.EXACT_MATCH,
            custom_metric_id=custom_id,
            weight_percent=100,
        )


def test_custom_metrics_use_native_deepeval_parameter_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deepeval.metrics

    captured: list[tuple[str, list[Any], Any]] = []

    class FakeMetric:
        score = 0.87555
        reason = "기준을 충족했습니다."

        def __init__(
            self,
            *,
            criteria: str,
            evaluation_params: list[object],
            **_kwargs: object,
        ) -> None:
            self.criteria = criteria
            self.evaluation_params = evaluation_params

        async def a_measure(self, test_case: object) -> float:
            captured.append((self.criteria, self.evaluation_params, test_case))
            return self.score

    monkeypatch.setattr(deepeval.metrics, "GEval", FakeMetric)
    result = asyncio.run(
        evaluate_selected_metrics(
            [
                EvaluationMetricDefinitionCreate(
                    custom_metric_id=uuid.uuid4(),
                    custom_metric_name="응답 친절도",
                    custom_metric_version=3,
                    custom_metric_prompt="{{input}}과 {{actual_output}}의 친절도를 평가",
                    required_keys=["input", "actual_output"],
                    weight_percent=100,
                )
            ],
            input_text="질문",
            actual_output="답변",
            expected_output="기대",
            model_name="judge-model",
        )
    )[0]
    assert captured[0][0] == "{{input}}과 {{actual_output}}의 친절도를 평가"
    assert [item.value for item in captured[0][1]] == ["input", "actual_output"]
    assert captured[0][2].actual_output == "답변"
    assert result.score == 87.555

    monkeypatch.setattr(deepeval.metrics, "ConversationalGEval", FakeMetric)
    conversational = asyncio.run(
        evaluate_conversation_metrics(
            [
                EvaluationMetricDefinitionCreate(
                    custom_metric_id=uuid.uuid4(),
                    custom_metric_name="대화 목표",
                    custom_metric_prompt="{{content}}와 {{expected_outcome}} 평가",
                    required_keys=["content", "expected_outcome"],
                    weight_percent=100,
                )
            ],
            turns=[("user", "질문"), ("assistant", "답변")],
            expected_outcome="1. 기대 답변",
            model_name="judge-model",
        )
    )[0]
    assert [item.value for item in captured[1][1]] == [
        "content",
        "expected_outcome",
    ]
    assert captured[1][2].expected_outcome == "1. 기대 답변"
    assert conversational.score == 87.555


def test_catalog_separates_twelve_single_and_four_multi_turn_metrics() -> None:
    single = [
        item
        for item in METRIC_CATALOG.values()
        if item.evaluation_mode == EvaluationMode.SINGLE_TURN
    ]
    multi = [
        item
        for item in METRIC_CATALOG.values()
        if item.evaluation_mode == EvaluationMode.MULTI_TURN
    ]
    assert len(single) == 12
    assert len(multi) == 4
    assert (
        METRIC_CATALOG[EvaluationMetricType.MISUSE].score_direction == "lower_is_better"
    )


def test_profile_rejects_mode_mixing_and_missing_required_config() -> None:
    with pytest.raises(ValidationError, match="wrong evaluation mode|evaluation mode"):
        EvaluationMetricProfileCreate(
            name="invalid",
            evaluation_mode=EvaluationMode.MULTI_TURN,
            metrics=[
                EvaluationMetricDefinitionCreate(
                    metric_type=EvaluationMetricType.TOXICITY, weight_percent=100
                )
            ],
        )
    with pytest.raises(ValidationError, match="chatbot_role"):
        EvaluationMetricProfileCreate(
            name="invalid role",
            evaluation_mode=EvaluationMode.MULTI_TURN,
            metrics=[
                EvaluationMetricDefinitionCreate(
                    metric_type=EvaluationMetricType.ROLE_ADHERENCE,
                    weight_percent=100,
                )
            ],
        )


def test_score_math_uses_zero_to_hundred_and_half_up() -> None:
    assert round_score(1.2345) == 1.235
    assert quality_score(0.234565, "higher_is_better") == 23.457
    assert quality_score(0.234565, "lower_is_better") == 76.544
    assert contribution_score(87.555, 33) == 28.893
    results = [
        MetricEvaluationResult(
            name="a",
            display_name="A",
            score=33.335,
            raw_score_ratio=0.33335,
            score_direction="higher_is_better",
            weight_percent=50,
            weighted_score=16.668,
        ),
        MetricEvaluationResult(
            name="b",
            display_name="B",
            score=66.665,
            raw_score_ratio=0.66665,
            score_direction="higher_is_better",
            weight_percent=50,
            weighted_score=33.333,
        ),
    ]
    assert aggregate_score(results) == 50
