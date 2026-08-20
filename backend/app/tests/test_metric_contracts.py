import pytest
from pydantic import ValidationError

from app.evaluation_metrics import (
    METRIC_CATALOG,
    MetricEvaluationResult,
    aggregate_score,
    contribution_score,
    quality_score,
    round_score,
)
from app.models import (
    EvaluationMetricDefinitionCreate,
    EvaluationMetricProfileCreate,
    EvaluationMetricType,
    EvaluationMode,
)


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
