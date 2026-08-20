import asyncio
import csv
import html
import importlib.util
import io
import json
import os
import re
import socket
import uuid
from difflib import SequenceMatcher
from typing import Any, Literal, cast
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import delete, func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import CurrentSuperuser, CurrentUser, SessionDep
from app.core.config import settings
from app.core.db import engine
from app.core.security import decrypt_evaluation_headers, encrypt_evaluation_headers
from app.cron_schedule import CronExpressionError, next_cron_run
from app.custom_metrics import (
    PLACEHOLDER_SYNTAX,
    SCOPE_ALLOWED_KEYS,
    CustomMetricPlaceholderError,
    ensure_required_values,
    parse_custom_metric_prompt,
)
from app.evaluation_jobs import enqueue_dataset_job
from app.evaluation_metrics import (
    METRIC_CATALOG,
    aggregate_score,
    catalog_definition,
    ensure_korean_reason,
    evaluate_conversation_metrics,
    evaluate_selected_metrics,
    round_score,
)
from app.models import (
    BulkDeleteRequest,
    CustomMetric,
    CustomMetricCreate,
    CustomMetricPlaceholderContract,
    CustomMetricPlaceholderContractsPublic,
    CustomMetricPublic,
    CustomMetricsPublic,
    CustomMetricUpdate,
    EvaluationComparison,
    EvaluationComparisonCreate,
    EvaluationComparisonMode,
    EvaluationComparisonPublic,
    EvaluationComparisonsPublic,
    EvaluationDataset,
    EvaluationDatasetCreate,
    EvaluationDatasetImportResult,
    EvaluationDatasetPublic,
    EvaluationDatasetRow,
    EvaluationDatasetRowCreate,
    EvaluationDatasetRowPublic,
    EvaluationDatasetRowsPublic,
    EvaluationDatasetRowUpdate,
    EvaluationDatasetScheduleCreate,
    EvaluationDatasetsPublic,
    EvaluationDatasetUpdate,
    EvaluationEndpoint,
    EvaluationEndpointCreate,
    EvaluationEndpointPublic,
    EvaluationEndpointsPublic,
    EvaluationEndpointUpdate,
    EvaluationJob,
    EvaluationJobPublic,
    EvaluationMetricCatalogItem,
    EvaluationMetricCatalogPublic,
    EvaluationMetricDefinitionCreate,
    EvaluationMetricDefinitionPublic,
    EvaluationMetricProfile,
    EvaluationMetricProfileCreate,
    EvaluationMetricProfileItem,
    EvaluationMetricProfilePublic,
    EvaluationMetricProfilesPublic,
    EvaluationMetricProfileUpdate,
    EvaluationMetricType,
    EvaluationMode,
    EvaluationRequestDocument,
    EvaluationRun,
    EvaluationRunMetricResult,
    EvaluationRunRow,
    EvaluationScenario,
    EvaluationScenarioCreate,
    EvaluationScenarioPublic,
    EvaluationScenarioRun,
    EvaluationScenarioRunTurn,
    EvaluationScenariosPublic,
    EvaluationScenarioTurn,
    EvaluationScenarioTurnCreate,
    EvaluationScenarioTurnPublic,
    EvaluationScenarioTurnsPublic,
    EvaluationScenarioUpdate,
    EvaluationSchedule,
    EvaluationScheduleBase,
    EvaluationScheduleCreate,
    EvaluationSchedulePublic,
    EvaluationSchedulesPublic,
    EvaluationScheduleTargetType,
    EvaluationScheduleType,
    EvaluationScheduleUpdate,
    EvaluationScope,
    Message,
    MultiTurnDatasetCaseDocument,
    MultiTurnDatasetDocument,
    SingleTurnDatasetCaseDocument,
    SingleTurnDatasetDocument,
    User,
    get_datetime_utc,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
MAX_DATASET_BYTES = 5 * 1024 * 1024
MAX_SAVED_DATASET_BYTES = 100 * 1024 * 1024
MAX_PAGE_SIZE = 200
MAX_EXECUTION_ROWS = 1_000
MAX_RESPONSE_BYTES = 1_000_000
Framework = Literal["local", "deepeval", "langfuse"]
_run_semaphore = asyncio.Semaphore(settings.EVALUATION_WORKER_CONCURRENCY)


class MetricScore(BaseModel):
    name: str
    score: float
    display_name: str | None = None
    weight_percent: int | None = None
    weighted_score: float | None = None
    raw_score_ratio: float | None = None
    score_direction: str | None = None
    reason: str | None = None
    error: str | None = None


class EvaluationRow(BaseModel):
    index: int
    input: str
    actual_output: str
    expected_output: str
    score: float
    passed: bool
    metrics: list[MetricScore]


class EvaluationSummary(BaseModel):
    framework: Framework
    evaluator: str
    total: int
    passed: int
    failed: int
    pass_rate: float
    average_score: float
    rows: list[EvaluationRow]


class IntegrationStatus(BaseModel):
    id: Framework
    label: str
    available: bool
    description: str


class IntegrationsResponse(BaseModel):
    data: list[IntegrationStatus]


class SavedRunRow(BaseModel):
    id: uuid.UUID
    dataset_row_id: uuid.UUID | None
    input: str
    expected_output: str
    actual_output: str
    response_status: int | None
    response_body: str | None
    score: float | None
    passed: bool
    metrics: list[MetricScore]
    error: str | None
    baseline_actual_output: str | None = None
    output_changed: bool | None = None
    score_delta: float | None = None


class SavedRunSummary(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    baseline_run_id: uuid.UUID | None
    evaluator: str
    total: int
    passed: int
    failed: int
    pass_rate: float
    average_score: float
    geval_available: bool
    metric_profile_id: uuid.UUID | None = None
    metric_profile_version: int | None = None
    dataset_name: str | None = None
    dataset_description: str | None = None
    executor_name: str | None = None
    created_at: str


class SavedRun(SavedRunSummary):
    rows: list[SavedRunRow]
    row_count: int


class SavedRunsPublic(BaseModel):
    data: list[SavedRunSummary]
    count: int


class ScenarioRunTurnPublic(BaseModel):
    id: uuid.UUID
    position: int
    identifier: str
    request_body: str
    actual_output: str
    expected_output: str
    response_status: int | None
    response_body: str | None
    score: float
    passed: bool
    reason: str | None
    error: str | None
    baseline_actual_output: str | None = None
    output_changed: bool | None = None
    score_delta: float | None = None


class ScenarioRunSummary(BaseModel):
    id: uuid.UUID
    scenario_id: uuid.UUID
    baseline_run_id: uuid.UUID | None
    total: int
    passed: int
    failed: int
    turn_average_score: float
    conversation_score: float | None
    conversation_reason: str | None
    overall_score: float
    overall_passed: bool
    overall_reason: str | None
    average_score: float
    evaluator: str
    metric_profile_id: uuid.UUID | None = None
    metric_profile_version: int | None = None
    metrics: list[MetricScore] = []
    geval_score: float | None
    geval_reason: str | None
    error: str | None
    created_at: str
    scenario_name: str | None = None
    scenario_description: str | None = None
    executor_name: str | None = None


class ScenarioRunPublic(ScenarioRunSummary):
    turns: list[ScenarioRunTurnPublic]


class ScenarioRunsPublic(BaseModel):
    data: list[ScenarioRunSummary]
    count: int


class PairwiseVerdict(BaseModel):
    winner: Literal["first", "second", "tie"]
    reason: str


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _token_recall(actual: str, expected: str) -> float:
    actual_tokens = set(_normalize(actual).split())
    expected_tokens = set(_normalize(expected).split())
    if not expected_tokens:
        return 1.0 if not actual_tokens else 0.0
    return len(actual_tokens & expected_tokens) / len(expected_tokens)


def _local_metric_reason(
    name: str, score: float, actual: str, expected: str
) -> str | None:
    if name == "exact_match":
        result = (
            "일치합니다"
            if _normalize(actual) == _normalize(expected)
            else "일치하지 않습니다"
        )
        return f"정규화된 실제 응답과 기대 응답이 {result}."
    if name == "similarity":
        return f"정규화된 응답의 문자 단위 유사도는 {score:.2f}점입니다."
    if name == "token_recall":
        actual_tokens = set(_normalize(actual).split())
        expected_tokens = set(_normalize(expected).split())
        matched = len(actual_tokens & expected_tokens)
        return (
            f"기대 응답 토큰 {len(expected_tokens)}개 중 {matched}개가 실제 응답에 "
            f"포함되어 있습니다. (점수 {score:.2f}점)"
        )
    return None


def _evaluate_row(row: dict[str, Any], index: int, threshold: float) -> EvaluationRow:
    missing = [
        field
        for field in ("input", "actual_output", "expected_output")
        if field not in row
    ]
    if missing:
        raise HTTPException(
            422, f"Row {index + 1} is missing fields: {', '.join(missing)}"
        )
    input_text, actual, expected = (
        str(row[key]) for key in ("input", "actual_output", "expected_output")
    )
    exact_match = float(_normalize(actual) == _normalize(expected)) * 100
    similarity = (
        SequenceMatcher(None, _normalize(actual), _normalize(expected)).ratio() * 100
    )
    token_recall = _token_recall(actual, expected) * 100
    score = round_score((exact_match + similarity + token_recall) / 3)
    similarity = round_score(similarity)
    token_recall = round_score(token_recall)
    return EvaluationRow(
        index=index,
        input=input_text,
        actual_output=actual,
        expected_output=expected,
        score=score,
        passed=score >= threshold,
        metrics=[
            MetricScore(
                name="exact_match",
                score=exact_match,
                reason=_local_metric_reason(
                    "exact_match", exact_match, actual, expected
                ),
            ),
            MetricScore(
                name="similarity",
                score=similarity,
                reason=_local_metric_reason("similarity", similarity, actual, expected),
            ),
            MetricScore(
                name="token_recall",
                score=token_recall,
                reason=_local_metric_reason(
                    "token_recall", token_recall, actual, expected
                ),
            ),
        ],
    )


def _openai_api_key() -> str | None:
    if api_key := os.getenv("OPENAI_API_KEY"):
        return api_key
    if settings.OPENAI_API_KEY:
        return settings.OPENAI_API_KEY.get_secret_value()
    return None


def _require_deepeval() -> None:
    if importlib.util.find_spec("deepeval") is None:
        raise ValueError("DeepEval is not installed on this server")
    if not (api_key := _openai_api_key()):
        raise ValueError("DeepEval requires OPENAI_API_KEY for LLM-as-a-judge scoring")
    # DeepEval discovers the API key from the process environment. Settings
    # loads it from the project's .env file, so bridge the two sources here.
    os.environ["OPENAI_API_KEY"] = api_key


def _validate_evaluator(value: str) -> None:
    if value not in {"deepeval", "local"}:
        raise HTTPException(422, "Evaluator must be 'deepeval' or 'local'")


def _ensure_evaluator_ready(value: str) -> None:
    _validate_evaluator(value)
    if value == "deepeval":
        try:
            _require_deepeval()
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc


def _deepeval_single(
    input_text: str, actual: str, expected: str, threshold: float
) -> MetricScore:
    """Score one natural-language answer with DeepEval's GEval metric."""
    _require_deepeval()
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, SingleTurnParams

    metric = GEval(
        name="자연어 응답 정확성",
        criteria=(
            "실제 응답이 기대 응답에 비추어 자연스럽고, 유용하며, 정확한지 "
            "평가하세요. 의미가 같다면 표현이 달라도 허용합니다. "
            "평가 이유는 반드시 자연스러운 한국어로 작성하세요."
        ),
        evaluation_params=[
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        threshold=threshold,
        model=settings.DEEPEVAL_MODEL,
    )
    metric.measure(
        LLMTestCase(
            input=input_text,
            actual_output=actual,
            expected_output=expected,
        )
    )
    return MetricScore(
        name="deepeval_geval",
        score=round_score(float(metric.score or 0) * 100),
        reason=ensure_korean_reason(
            str(metric.reason or "")[:2_000] or None,
            float(metric.score or 0) * 100,
            settings.DEEPEVAL_MODEL,
        ),
    )


async def _evaluate_live_row(
    input_text: str,
    actual: str,
    expected: str,
    index: int,
    threshold: float,
    evaluator: str,
    metric_definitions: list[EvaluationMetricDefinitionCreate] | None = None,
) -> EvaluationRow:
    if evaluator == "local":
        return _evaluate_row(
            {"input": input_text, "actual_output": actual, "expected_output": expected},
            index,
            threshold,
        )
    if evaluator != "deepeval":
        raise ValueError("Evaluator must be 'deepeval' or 'local'")
    if metric_definitions:
        try:
            composite_results = await evaluate_selected_metrics(
                metric_definitions,
                input_text=input_text,
                actual_output=actual,
                expected_output=expected,
                model_name=settings.DEEPEVAL_MODEL,
            )
        except Exception as exc:
            raise ValueError(f"DeepEval metrics failed: {exc}") from exc
        metrics = [
            MetricScore(
                name=result.name,
                display_name=result.display_name,
                score=result.score,
                weight_percent=result.weight_percent,
                weighted_score=result.weighted_score,
                raw_score_ratio=result.raw_score_ratio,
                score_direction=result.score_direction,
                reason=result.reason,
                error=result.error,
            )
            for result in composite_results
        ]
        final_score = aggregate_score(composite_results)
        return EvaluationRow(
            index=index,
            input=input_text,
            actual_output=actual,
            expected_output=expected,
            score=final_score,
            passed=final_score >= threshold,
            metrics=metrics,
        )
    score = await asyncio.to_thread(
        _deepeval_single, input_text, actual, expected, threshold
    )
    return EvaluationRow(
        index=index,
        input=input_text,
        actual_output=actual,
        expected_output=expected,
        score=score.score,
        passed=score.score >= threshold,
        metrics=[score],
    )


def parse_dataset(filename: str, content: bytes) -> list[dict[str, Any]]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "Dataset must be UTF-8 encoded")
    suffix = filename.lower().rsplit(".", 1)[-1]
    try:
        if suffix == "csv":
            rows: Any = list(csv.DictReader(io.StringIO(decoded)))
        elif suffix == "json":
            payload = json.loads(decoded)
            rows = payload.get("data") if isinstance(payload, dict) else payload
        else:
            raise HTTPException(415, "Only .csv and .json datasets are supported")
    except (csv.Error, json.JSONDecodeError) as exc:
        raise HTTPException(422, f"Invalid dataset: {exc}")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(422, "Dataset must contain at least one row")
    if not all(isinstance(row, dict) for row in rows):
        raise HTTPException(422, "Every dataset row must be an object")
    return cast(list[dict[str, Any]], rows)


def _import_rows(filename: str, content: bytes) -> list[EvaluationDatasetRowCreate]:
    if not filename.lower().endswith(".json"):
        raise HTTPException(415, "Only .json datasets are supported")
    output: list[EvaluationDatasetRowCreate] = []
    for index, row in enumerate(parse_dataset(filename, content)):
        if not isinstance(row.get("input"), str) or not isinstance(
            row.get("expected_output"), str
        ):
            raise HTTPException(
                422,
                f"Row {index + 1} must include string fields 'input' and 'expected_output'",
            )
        output.append(
            EvaluationDatasetRowCreate(
                input=row["input"], expected_output=row["expected_output"]
            )
        )
    return output


def _endpoint_public(endpoint: EvaluationEndpoint) -> EvaluationEndpointPublic:
    return EvaluationEndpointPublic(
        **endpoint.model_dump(exclude={"encrypted_headers"}),
        headers_configured=bool(endpoint.encrypted_headers),
    )


def _reject_sensitive_dataset_headers(headers: dict[str, str]) -> None:
    sensitive = {"authorization", "cookie", "set-cookie", "x-api-key", "api-key"}
    if any(
        key.lower() in sensitive or "token" in key.lower() or "secret" in key.lower()
        for key in headers
    ):
        raise HTTPException(
            422,
            "Sensitive request headers must be configured on the managed A server",
        )


def _validate_external_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise HTTPException(
            422, "Evaluation endpoints must be credential-free HTTP(S) URLs"
        )
    if settings.ENVIRONMENT == "local":
        return value.rstrip("/")
    if parsed.scheme != "https":
        raise HTTPException(
            422, "Evaluation endpoints must use HTTPS outside local development"
        )
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise HTTPException(422, "Local or internal evaluation hosts are not allowed")
    # Reject literal and DNS-resolved private targets. This is repeated when a
    # run starts so a server cannot be changed to an internal address after it
    # was approved by an administrator.
    import ipaddress

    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise HTTPException(
                422, "Private or internal evaluation hosts are not allowed"
            )
    except ValueError:
        try:
            resolved = socket.getaddrinfo(
                host, parsed.port or 443, type=socket.SOCK_STREAM
            )
        except socket.gaierror as exc:
            raise HTTPException(
                422, "Evaluation endpoint host could not be resolved"
            ) from exc
        if not resolved:
            raise HTTPException(422, "Evaluation endpoint host could not be resolved")
        for item in resolved:
            if not ipaddress.ip_address(item[4][0]).is_global:
                raise HTTPException(
                    422, "Private or internal evaluation hosts are not allowed"
                )
    return value.rstrip("/")


def _assert_url_allowed(endpoint: EvaluationEndpoint, url: str) -> str:
    candidate = _validate_external_url(url)
    base = urlsplit(endpoint.base_url)
    target = urlsplit(candidate)
    if (target.scheme, target.hostname, target.port) != (
        base.scheme,
        base.hostname,
        base.port,
    ):
        raise HTTPException(422, "Scenario URL must use the selected allowed server")
    return candidate


def _relative_turn_url(endpoint: EvaluationEndpoint, url: str) -> str:
    if urlsplit(url).scheme:
        absolute = _assert_url_allowed(endpoint, url)
        parsed = urlsplit(absolute)
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")
    if not url.startswith("/") or url.startswith("//"):
        raise HTTPException(422, "Scenario turn URL must be an origin-relative path")
    return url


def _turn_endpoint_url(endpoint: EvaluationEndpoint, relative_url: str) -> str:
    if urlsplit(relative_url).scheme:
        relative_url = _relative_turn_url(endpoint, relative_url)
    candidate = urljoin(endpoint.base_url.rstrip("/") + "/", relative_url.lstrip("/"))
    return _assert_url_allowed(endpoint, candidate)


async def _endpoint_or_422(
    session: SessionDep, endpoint_id: uuid.UUID | None
) -> EvaluationEndpoint:
    if not endpoint_id:
        raise HTTPException(
            422, "Select an administrator-managed A server before running"
        )
    endpoint = await session.get(EvaluationEndpoint, endpoint_id)
    if not endpoint or not endpoint.is_active:
        raise HTTPException(422, "The selected A server is unavailable")
    _validate_external_url(endpoint.base_url)
    return endpoint


async def _dataset_or_404(
    session: SessionDep, user: CurrentUser, dataset_id: uuid.UUID
) -> EvaluationDataset:
    dataset = await session.get(EvaluationDataset, dataset_id)
    if not dataset or dataset.evaluation_type != "single_turn":
        raise HTTPException(404, "Evaluation dataset not found")
    if not user.is_superuser and dataset.owner_id != user.id:
        raise HTTPException(403, "Not enough permissions")
    return dataset


async def _scenario_or_404(
    session: SessionDep, user: CurrentUser, scenario_id: uuid.UUID
) -> EvaluationScenario:
    scenario = await session.get(EvaluationScenario, scenario_id)
    if not scenario:
        raise HTTPException(404, "Evaluation scenario not found")
    if not user.is_superuser and scenario.owner_id != user.id:
        raise HTTPException(403, "Not enough permissions")
    return scenario


async def _count(session: SessionDep, model: Any, *conditions: Any) -> int:
    return int(
        (await session.exec(select(func.count(model.id)).where(*conditions))).one()
    )


async def _stage_run_evidence(
    session: SessionDep,
    rows: list[EvaluationRunRow],
    metric_results: list[EvaluationRunMetricResult],
) -> None:
    """Insert parent run rows before their normalized metric results."""
    session.add_all(rows)
    await session.flush()
    session.add_all(metric_results)


def _metric_definition(
    item: EvaluationMetricProfileItem,
) -> EvaluationMetricDefinitionCreate:
    return EvaluationMetricDefinitionCreate(
        metric_type=EvaluationMetricType(item.key)
        if item.custom_metric_id is None
        else None,
        custom_metric_id=item.custom_metric_id,
        weight_percent=item.weight_percent,
        config=item.config,
        custom_instruction=item.custom_instruction,
        custom_metric_name=item.display_name if item.custom_metric_id else None,
        custom_metric_version=item.custom_metric_version,
        custom_metric_prompt=item.custom_metric_prompt,
        required_keys=item.required_keys,
    )


def _custom_metric_conflict(
    *, metric_name: str, metric_id: uuid.UUID, reason: str
) -> HTTPException:
    return HTTPException(
        409,
        (
            f"CustomMetric '{metric_name}' ({metric_id})의 저장된 placeholder 상태가 "
            f"올바르지 않습니다: {reason}. 메트릭 프롬프트를 현재 범위의 허용 key로 "
            "다시 저장한 뒤 프로필을 새 버전으로 저장하세요."
        ),
    )


def _validated_profile_custom_metric_keys(
    item: EvaluationMetricProfileItem,
) -> list[str]:
    assert item.custom_metric_id is not None
    if not item.custom_metric_prompt or not item.custom_metric_scope:
        raise _custom_metric_conflict(
            metric_name=item.display_name,
            metric_id=item.custom_metric_id,
            reason="프롬프트 또는 평가 범위 스냅샷이 없습니다",
        )
    try:
        parsed = list(
            parse_custom_metric_prompt(
                item.custom_metric_prompt, item.custom_metric_scope
            )
        )
    except (CustomMetricPlaceholderError, ValueError) as exc:
        raise _custom_metric_conflict(
            metric_name=item.display_name,
            metric_id=item.custom_metric_id,
            reason=str(exc),
        ) from exc
    if parsed != item.required_keys:
        raise _custom_metric_conflict(
            metric_name=item.display_name,
            metric_id=item.custom_metric_id,
            reason=(
                "required_keys 스냅샷이 프롬프트와 일치하지 않습니다 "
                f"(저장값: {item.required_keys}, 계산값: {parsed})"
            ),
        )
    return parsed


def _validated_current_custom_metric_keys(metric: CustomMetric) -> list[str]:
    try:
        return list(
            parse_custom_metric_prompt(metric.prompt, metric.evaluation_scope.value)
        )
    except (CustomMetricPlaceholderError, ValueError) as exc:
        raise _custom_metric_conflict(
            metric_name=metric.name,
            metric_id=metric.id,
            reason=str(exc),
        ) from exc


async def _metric_profile_items(
    session: SessionDep, profile_id: uuid.UUID
) -> list[EvaluationMetricProfileItem]:
    return list(
        (
            await session.exec(
                select(EvaluationMetricProfileItem)
                .where(EvaluationMetricProfileItem.profile_id == profile_id)
                .order_by(col(EvaluationMetricProfileItem.position))
            )
        ).all()
    )


async def _metric_profile_or_422(
    session: SessionDep,
    profile_id: uuid.UUID,
    *,
    require_active: bool = True,
    expected_mode: EvaluationMode | None = None,
    expected_scope: EvaluationScope | None = None,
) -> tuple[EvaluationMetricProfile, list[EvaluationMetricProfileItem]]:
    profile = await session.get(EvaluationMetricProfile, profile_id)
    if not profile:
        raise HTTPException(422, "Selected metric profile does not exist")
    if require_active and not profile.is_active:
        raise HTTPException(422, "Selected metric profile is inactive")
    profile_scope = EvaluationScope(profile.evaluation_scope)
    if expected_scope is None and expected_mode is not None:
        expected_scope = EvaluationScope(expected_mode.value)
    if expected_scope is not None and profile_scope != expected_scope:
        raise HTTPException(
            422, "Selected metric profile has the wrong evaluation scope"
        )
    items = await _metric_profile_items(session, profile.id)
    if not items:
        raise HTTPException(422, "Selected metric profile has no metrics")
    if sum(item.weight_percent for item in items) != 100:
        raise HTTPException(422, "Selected metric profile weights must add up to 100")
    if len({item.key for item in items}) != len(items):
        raise HTTPException(422, "Selected metric profile contains duplicate metrics")
    for item in items:
        if item.custom_metric_id is not None:
            if item.custom_metric_scope != profile_scope.value:
                raise HTTPException(
                    422, "Custom metric scope does not match the selected profile"
                )
            _validated_profile_custom_metric_keys(item)
        else:
            try:
                metric_type = EvaluationMetricType(item.key)
            except ValueError as exc:
                raise HTTPException(
                    422, "Selected metric profile contains an unsupported metric"
                ) from exc
            metric_mode = catalog_definition(metric_type).evaluation_mode
            expected_item_mode = (
                EvaluationMode.MULTI_TURN
                if profile_scope == EvaluationScope.MULTI_TURN
                else EvaluationMode.SINGLE_TURN
            )
            if metric_mode != expected_item_mode:
                raise HTTPException(
                    422, "Built-in metric scope does not match the selected profile"
                )
    return profile, items


def _metric_profile_public(
    profile: EvaluationMetricProfile, items: list[EvaluationMetricProfileItem]
) -> EvaluationMetricProfilePublic:
    return EvaluationMetricProfilePublic(
        **profile.model_dump(),
        metrics=[_metric_definition_public(item) for item in items],
    )


def _metric_definition_public(
    item: EvaluationMetricProfileItem,
) -> EvaluationMetricDefinitionPublic:
    definition = _metric_definition(item)
    if item.custom_metric_id is not None:
        return EvaluationMetricDefinitionPublic(
            id=item.id,
            position=item.position,
            display_name=item.display_name,
            description=item.criteria,
            required_fields=item.required_keys,
            score_direction="higher_is_better",
            uses_llm=True,
            docs_url="https://deepeval.com/docs/metrics-llm-evals",
            evaluation_mode=(
                EvaluationMode.MULTI_TURN
                if item.custom_metric_scope == EvaluationScope.MULTI_TURN.value
                else EvaluationMode.SINGLE_TURN
            ),
            required_config=[],
            supports_custom_instruction=False,
            **definition.model_dump(),
        )
    assert definition.metric_type is not None
    catalog = catalog_definition(definition.metric_type)
    return EvaluationMetricDefinitionPublic(
        id=item.id,
        position=item.position,
        display_name=catalog.display_name,
        description=catalog.description,
        required_fields=list(catalog.required_fields),
        score_direction=catalog.score_direction,
        uses_llm=catalog.uses_llm,
        docs_url=catalog.docs_url,
        evaluation_mode=catalog.evaluation_mode,
        required_config=list(catalog.required_config),
        supports_custom_instruction=catalog.supports_custom_instruction,
        **definition.model_dump(),
    )


def _metric_profile_snapshot(
    profile: EvaluationMetricProfile, items: list[EvaluationMetricProfileItem]
) -> dict[str, object]:
    return {
        "id": str(profile.id),
        "name": profile.name,
        "version": profile.version,
        "evaluation_mode": profile.evaluation_mode,
        "evaluation_scope": profile.evaluation_scope,
        "metrics": [
            {
                "metric_type": item.key,
                "display_name": item.display_name,
                "weight_percent": item.weight_percent,
                "config": item.config,
                "custom_instruction": item.custom_instruction,
                "custom_metric_id": (
                    str(item.custom_metric_id) if item.custom_metric_id else None
                ),
                "custom_metric_version": item.custom_metric_version,
                "custom_metric_prompt": item.custom_metric_prompt,
                "required_keys": (
                    _validated_profile_custom_metric_keys(item)
                    if item.custom_metric_id is not None
                    else item.required_keys
                ),
            }
            for item in items
        ],
    }


def _dataset_public(
    dataset: EvaluationDataset,
    rows: list[EvaluationDatasetRow],
    row_count: int | None = None,
) -> EvaluationDatasetPublic:
    return EvaluationDatasetPublic(
        **dataset.model_dump(
            exclude={"endpoint_url", "headers", "method", "threshold"}
        ),
        threshold=float(dataset.threshold),
        test_type="single_turn",
        row_count=len(rows) if row_count is None else row_count,
        rows=[EvaluationDatasetRowPublic.model_validate(row) for row in rows],
    )


def _replace_variables(value: Any, variables: dict[str, Any]) -> Any:
    if isinstance(value, str):
        if value in {f"{{{{{key}}}}}" for key in variables}:
            key = value[2:-2]
            return variables[key]
        for key, replacement in variables.items():
            placeholder = f"{{{{{key}}}}}"
            if placeholder in value:
                rendered = (
                    replacement
                    if isinstance(replacement, str)
                    else json.dumps(replacement, ensure_ascii=False)
                )
                value = value.replace(placeholder, rendered)
        return value
    if isinstance(value, list):
        return [_replace_variables(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _replace_variables(item, variables) for key, item in value.items()}
    return value


def _request_body(template: str, variables: dict[str, Any]) -> tuple[Any, bool]:
    try:
        return _replace_variables(json.loads(template), variables), True
    except json.JSONDecodeError:
        return _replace_variables(template, variables), False


def _extract_response(value: Any, path: str | None) -> Any:
    current = value
    if not path:
        return current
    if path.startswith("/"):
        segments = [
            token.replace("~1", "/").replace("~0", "~") for token in path.split("/")[1:]
        ]
    else:
        # Compatibility for datasets saved before RFC 6901 pointers were exposed.
        segments = path.split(".")
    for segment in segments:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif (
            isinstance(current, list)
            and segment.isdigit()
            and int(segment) < len(current)
        ):
            current = current[int(segment)]
        else:
            raise ValueError(f"Actual-output JSON Pointer '{path}' was not found")
    return current


async def _call_endpoint(
    url: str,
    headers: dict[str, str],
    template: str,
    response_path: str | None,
    variables: dict[str, Any],
    json_overrides: dict[str, Any] | None = None,
) -> tuple[int, str, str, str]:
    body, is_json = _request_body(template, variables)
    if json_overrides:
        if not is_json or not isinstance(body, dict):
            raise ValueError("A multi-turn request body must be a JSON object")
        body = {**body, **json_overrides}
    async with httpx.AsyncClient(
        timeout=settings.EVALUATION_REQUEST_TIMEOUT_SECONDS, follow_redirects=False
    ) as client:
        response = await client.post(
            url,
            headers=headers,
            json=body if is_json else None,
            content=None if is_json else str(body),
        )
    response_body = response.text[:MAX_RESPONSE_BYTES]
    try:
        payload: Any = response.json()
    except json.JSONDecodeError:
        payload = response.text
    extracted = _extract_response(payload, response_path)
    actual = (
        extracted
        if isinstance(extracted, str)
        else json.dumps(extracted, ensure_ascii=False)
    )
    request_body = json.dumps(body, ensure_ascii=False) if is_json else str(body)
    return response.status_code, response_body, actual, request_body


def _run_summary(
    run: EvaluationRun,
    dataset: EvaluationDataset | None = None,
    executor: User | None = None,
) -> SavedRunSummary:
    return SavedRunSummary(
        **run.model_dump(exclude={"created_at"}),
        dataset_name=dataset.name if dataset else None,
        dataset_description=(dataset.description or "")[:20] if dataset else None,
        executor_name=(executor.full_name or executor.email) if executor else None,
        created_at=run.created_at.isoformat(),
    )


def _saved_run(
    run: EvaluationRun,
    rows: list[EvaluationRunRow],
    baseline_rows: list[EvaluationRunRow] | None = None,
    dataset: EvaluationDataset | None = None,
    executor: User | None = None,
) -> SavedRun:
    baseline_by_dataset = {row.dataset_row_id: row for row in baseline_rows or []}
    serialized: list[SavedRunRow] = []
    for row in rows:
        baseline = baseline_by_dataset.get(row.dataset_row_id)
        metrics = [MetricScore.model_validate(metric) for metric in (row.metrics or [])]
        for metric in metrics:
            if metric.reason is None:
                metric.reason = _local_metric_reason(
                    metric.name,
                    metric.score,
                    row.actual_output,
                    row.expected_output,
                )
        serialized.append(
            SavedRunRow(
                **row.model_dump(exclude={"metrics"}),
                metrics=metrics,
                baseline_actual_output=baseline.actual_output if baseline else None,
                output_changed=(row.actual_output != baseline.actual_output)
                if baseline
                else None,
                score_delta=(
                    round_score(row.score - baseline.score, clamp=False)
                    if baseline and row.score is not None and baseline.score is not None
                    else None
                ),
            )
        )
    return SavedRun(
        **_run_summary(run, dataset, executor).model_dump(),
        rows=serialized,
        row_count=len(serialized),
    )


def _html_report(
    run: SavedRun,
    dataset: EvaluationDataset,
    executor: User,
    metric_profile_snapshot: dict[str, object] | None,
) -> str:
    def escaped(value: object | None) -> str:
        return html.escape("" if value is None else str(value), quote=True)

    def score(value: float | None) -> str:
        return f"{value:.2f}점" if value is not None else "점수 없음"

    def required_keys(item: dict[Any, Any]) -> str:
        value = item.get("required_keys")
        return ", ".join(str(key) for key in value) if isinstance(value, list) else "-"

    profile_metrics = []
    profile_name = "-"
    profile_scope = "-"
    if isinstance(metric_profile_snapshot, dict):
        profile_name = str(metric_profile_snapshot.get("name") or "-")
        profile_scope = str(metric_profile_snapshot.get("evaluation_scope") or "-")
        raw_metrics = metric_profile_snapshot.get("metrics")
        if isinstance(raw_metrics, list):
            profile_metrics = [item for item in raw_metrics if isinstance(item, dict)]
    profile_rows = "".join(
        "<tr>"
        f"<td>{escaped(item.get('display_name') or item.get('metric_type') or item.get('key'))}</td>"
        f"<td>{escaped(item.get('weight_percent'))}%</td>"
        f"<td>{escaped(item.get('custom_metric_id') or '-')}</td>"
        f"<td>{escaped(item.get('custom_metric_version') or '-')}</td>"
        f"<td>{escaped(required_keys(item))}</td>"
        f"<td>{escaped(item.get('custom_metric_prompt') or '-')}</td>"
        "</tr>"
        for item in profile_metrics
    )
    evidence = []
    for index, row in enumerate(run.rows, start=1):
        metric_rows = "".join(
            "<tr>"
            f"<td>{escaped(metric.display_name or metric.name)}</td>"
            f"<td>{f'{metric.weight_percent}%' if metric.weight_percent is not None else '-'}</td>"
            f"<td>{score(metric.score)}</td>"
            f"<td>{score(metric.weighted_score) if metric.weighted_score is not None else '-'}</td>"
            f"<td>{escaped(metric.error or metric.reason or '판정 사유 없음')}</td>"
            "</tr>"
            for metric in row.metrics
        )
        evidence.append(
            f"""
            <section class="evidence">
              <h3>#{index} · {"통과" if row.passed else "실패"} · {score(row.score)}</h3>
              <dl><dt>Input</dt><dd>{escaped(row.input)}</dd>
              <dt>Expected output</dt><dd>{escaped(row.expected_output)}</dd>
              <dt>Actual output</dt><dd>{escaped(row.actual_output)}</dd></dl>
              {f'<p class="error">실행 오류: {escaped(row.error)}</p>' if row.error else ""}
              <table><thead><tr><th>평가지표</th><th>가중치</th><th>점수</th><th>기여점수</th><th>판정 사유</th></tr></thead>
              <tbody>{metric_rows or '<tr><td colspan="5">지표별 결과가 없습니다.</td></tr>'}</tbody></table>
            </section>
            """
        )
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escaped(dataset.name)} 평가 결과표</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#292524;margin:0;background:#fafaf9}}main{{max-width:1120px;margin:0 auto;padding:32px}}h1{{margin-bottom:6px}}h2{{margin-top:32px}}.muted{{color:#78716c}}.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}}.card,.evidence{{background:white;border:1px solid #e7e5e4;border-radius:10px;padding:16px}}.value{{font-size:20px;font-weight:700;margin-top:6px}}table{{width:100%;border-collapse:collapse;margin-top:12px}}th,td{{border:1px solid #e7e5e4;padding:9px;text-align:left;vertical-align:top}}th{{background:#f5f5f4}}dl{{display:grid;grid-template-columns:150px 1fr;gap:8px}}dt{{font-weight:600}}dd{{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}}.evidence{{margin:14px 0}}.error{{color:#b91c1c}}@media(max-width:700px){{main{{padding:16px}}.summary{{grid-template-columns:1fr 1fr}}table{{display:block;overflow-x:auto}}dl{{grid-template-columns:1fr}}}}@media print{{body{{background:white}}.evidence{{break-inside:avoid}}}}
</style></head><body><main>
<header><p class="muted">EvaluationHub · 싱글턴 품질 테스트</p><h1>{escaped(dataset.name)}</h1><p>{escaped(dataset.description or "설명 없음")}</p></header>
<div class="summary"><div class="card"><span class="muted">실행자</span><div class="value">{escaped(executor.full_name or executor.email)}</div></div><div class="card"><span class="muted">실행시각</span><div class="value">{escaped(run.created_at)}</div></div><div class="card"><span class="muted">종합 점수</span><div class="value">{score(run.average_score)}</div></div><div class="card"><span class="muted">통과 기준</span><div class="value">{score(float(dataset.threshold))}</div></div></div>
<p>총점 = Σ(메트릭 0~100 점수 × 가중치 / 100), 반올림은 ROUND_HALF_UP 소수점 셋째 자리입니다. 통과 {run.passed}/{run.total}.</p>
<h2>평가 프로파일</h2><p class="muted">{escaped(profile_name)} · 범위 {escaped(profile_scope)} · 실행 스냅샷 v{escaped(run.metric_profile_version or "-")}</p><table><thead><tr><th>평가지표</th><th>가중치</th><th>CustomMetric ID</th><th>버전</th><th>필요 키</th><th>프롬프트</th></tr></thead><tbody>{profile_rows or '<tr><td colspan="6">지표 프로파일 스냅샷이 없습니다.</td></tr>'}</tbody></table>
<h2>행별 결과</h2>{"".join(evidence)}
</main></body></html>"""


def _scenario_public(
    scenario: EvaluationScenario,
    turns: list[EvaluationScenarioTurn],
    count: int | None = None,
) -> EvaluationScenarioPublic:
    return EvaluationScenarioPublic(
        **scenario.model_dump(exclude={"threshold"}),
        threshold=float(scenario.threshold),
        test_type="multi_turn",
        evaluation_type="multi_turn",
        turn_count=len(turns) if count is None else count,
        turns=[
            EvaluationScenarioTurnPublic(
                id=turn.id,
                position=turn.position,
                identifier=turn.identifier,
                url=turn.url,
                headers_configured=bool(turn.encrypted_headers),
                body_template=turn.body_template,
                response_path=turn.response_path,
                expected_output=turn.expected_output,
            )
            for turn in turns
        ],
    )


def _scenario_run(
    run: EvaluationScenarioRun,
    turns: list[EvaluationScenarioRunTurn],
    baseline_turns: list[EvaluationScenarioRunTurn] | None = None,
    scenario: EvaluationScenario | None = None,
    executor: User | None = None,
) -> ScenarioRunPublic:
    baseline_by_identifier = {turn.identifier: turn for turn in baseline_turns or []}
    return ScenarioRunPublic(
        **run.model_dump(exclude={"created_at"}),
        conversation_score=run.geval_score,
        conversation_reason=run.geval_reason,
        created_at=run.created_at.isoformat(),
        scenario_name=scenario.name if scenario else None,
        scenario_description=(scenario.description or "")[:20] if scenario else None,
        executor_name=(executor.full_name or executor.email) if executor else None,
        turns=[
            ScenarioRunTurnPublic(
                **turn.model_dump(),
                baseline_actual_output=baseline.actual_output if baseline else None,
                output_changed=(turn.actual_output != baseline.actual_output)
                if baseline
                else None,
                score_delta=(
                    round_score(turn.score - baseline.score, clamp=False)
                    if baseline
                    else None
                ),
            )
            for turn in turns
            for baseline in [baseline_by_identifier.get(turn.identifier)]
        ],
    )


def _scenario_run_summary(
    run: EvaluationScenarioRun,
    scenario: EvaluationScenario,
    executor: User | None,
) -> ScenarioRunSummary:
    return ScenarioRunSummary(
        **run.model_dump(exclude={"created_at"}),
        conversation_score=run.geval_score,
        conversation_reason=run.geval_reason,
        created_at=run.created_at.isoformat(),
        scenario_name=scenario.name,
        scenario_description=(scenario.description or "")[:20],
        executor_name=(executor.full_name or executor.email) if executor else None,
    )


def _conversation_user_content(request_body: str) -> str:
    """Return the new user utterance from a generic JSON request body."""
    try:
        payload = json.loads(request_body)
    except json.JSONDecodeError:
        return request_body
    if isinstance(payload, dict):
        if isinstance(payload.get("message"), str):
            return str(payload["message"])
        messages = payload.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if (
                    isinstance(message, dict)
                    and message.get("role") == "user"
                    and isinstance(message.get("content"), str)
                ):
                    return str(message.get("content"))
    return request_body


@router.get("/integrations", response_model=IntegrationsResponse)
async def read_integrations(_current_user: CurrentUser) -> IntegrationsResponse:
    deepeval_ready = bool(importlib.util.find_spec("deepeval") and _openai_api_key())
    return IntegrationsResponse(
        data=[
            IntegrationStatus(
                id="local",
                label="Local baseline",
                available=True,
                description="Exact match, similarity, and token recall.",
            ),
            IntegrationStatus(
                id="deepeval",
                label="GEval / DeepEval",
                available=deepeval_ready,
                description="Natural-language GEval scoring. Set OPENAI_API_KEY to enable the judge.",
            ),
            IntegrationStatus(
                id="langfuse",
                label="Langfuse",
                available=False,
                description="Project credentials are required.",
            ),
        ]
    )


def _custom_metric_public(metric: CustomMetric) -> CustomMetricPublic:
    return CustomMetricPublic(
        **metric.model_dump(),
        required_keys=list(
            parse_custom_metric_prompt(metric.prompt, metric.evaluation_scope.value)
        ),
    )


@router.get(
    "/custom-metric-placeholder-contracts",
    response_model=CustomMetricPlaceholderContractsPublic,
)
async def read_custom_metric_placeholder_contracts(
    _user: CurrentUser,
) -> CustomMetricPlaceholderContractsPublic:
    data = [
        CustomMetricPlaceholderContract(
            evaluation_scope=scope,
            syntax=PLACEHOLDER_SYNTAX,
            requires_at_least_one=True,
            allowed_keys=list(SCOPE_ALLOWED_KEYS[scope.value]),
        )
        for scope in EvaluationScope
    ]
    return CustomMetricPlaceholderContractsPublic(data=data, count=len(data))


@router.get("/custom-metrics", response_model=CustomMetricsPublic)
async def read_custom_metrics(
    session: SessionDep,
    _user: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=200),
    evaluation_scope: EvaluationScope | None = None,
    is_active: bool | None = None,
) -> CustomMetricsPublic:
    statement = select(CustomMetric).order_by(col(CustomMetric.updated_at).desc())
    if evaluation_scope is not None:
        statement = statement.where(
            CustomMetric.evaluation_scope == evaluation_scope.value
        )
    if is_active is not None:
        statement = statement.where(CustomMetric.is_active == is_active)
    count = int(
        (
            await session.exec(select(func.count()).select_from(statement.subquery()))
        ).one()
    )
    metrics = list((await session.exec(statement.offset(offset).limit(limit))).all())
    return CustomMetricsPublic(
        data=[_custom_metric_public(metric) for metric in metrics], count=count
    )


@router.post("/custom-metrics", response_model=CustomMetricPublic)
async def create_custom_metric(
    metric_in: CustomMetricCreate, session: SessionDep, user: CurrentUser
) -> CustomMetricPublic:
    metric = CustomMetric(
        **metric_in.model_dump(), created_by_id=user.id, updated_by_id=user.id
    )
    session.add(metric)
    await session.commit()
    await session.refresh(metric)
    return _custom_metric_public(metric)


@router.put("/custom-metrics/{metric_id}", response_model=CustomMetricPublic)
async def update_custom_metric(
    metric_id: uuid.UUID,
    metric_in: CustomMetricUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> CustomMetricPublic:
    metric = await session.get(CustomMetric, metric_id)
    if metric is None:
        raise HTTPException(404, "Custom metric not found")
    if (
        metric_in.expected_version is not None
        and metric_in.expected_version != metric.version
    ):
        raise HTTPException(409, "Custom metric was modified by another user")
    metric.sqlmodel_update(metric_in.model_dump(exclude={"expected_version"}))
    metric.version += 1
    metric.updated_by_id = user.id
    metric.updated_at = get_datetime_utc()
    session.add(metric)
    await session.commit()
    await session.refresh(metric)
    return _custom_metric_public(metric)


@router.delete("/custom-metrics/{metric_id}")
async def delete_custom_metric(
    metric_id: uuid.UUID, session: SessionDep, _user: CurrentUser
) -> Message:
    metric = await session.get(CustomMetric, metric_id)
    if metric is None:
        raise HTTPException(404, "Custom metric not found")
    reference_count = int(
        (
            await session.exec(
                select(func.count())
                .select_from(EvaluationMetricProfileItem)
                .where(EvaluationMetricProfileItem.custom_metric_id == metric.id)
            )
        ).one()
    )
    if reference_count:
        raise HTTPException(409, "Referenced custom metrics cannot be deleted")
    await session.delete(metric)
    await session.commit()
    return Message(message="Custom metric deleted successfully")


async def _build_metric_profile_items(
    session: SessionDep,
    profile: EvaluationMetricProfile,
    metrics: list[EvaluationMetricDefinitionCreate],
) -> list[EvaluationMetricProfileItem]:
    items: list[EvaluationMetricProfileItem] = []
    profile_scope = EvaluationScope(profile.evaluation_scope)
    for position, metric in enumerate(metrics):
        if metric.custom_metric_id is not None:
            custom = await session.get(CustomMetric, metric.custom_metric_id)
            if custom is None:
                raise HTTPException(422, "Selected custom metric does not exist")
            if not custom.is_active:
                raise HTTPException(422, "Selected custom metric is inactive")
            if custom.evaluation_scope != profile_scope:
                raise HTTPException(
                    422, "Custom metric scope must match the profile scope"
                )
            required_keys = _validated_current_custom_metric_keys(custom)
            items.append(
                EvaluationMetricProfileItem(
                    profile_id=profile.id,
                    position=position,
                    key=f"custom:{custom.id}",
                    display_name=custom.name,
                    criteria=custom.description or "사용자 정의 G-Eval 메트릭",
                    weight_percent=metric.weight_percent,
                    evaluation_params=required_keys,
                    custom_metric_id=custom.id,
                    custom_metric_version=custom.version,
                    custom_metric_prompt=custom.prompt,
                    custom_metric_scope=custom.evaluation_scope.value,
                    required_keys=required_keys,
                )
            )
            continue
        if metric.metric_type is None:
            raise HTTPException(422, "Metric identity is missing")
        catalog = catalog_definition(metric.metric_type)
        expected_mode = (
            EvaluationMode.MULTI_TURN
            if profile_scope == EvaluationScope.MULTI_TURN
            else EvaluationMode.SINGLE_TURN
        )
        if catalog.evaluation_mode != expected_mode:
            raise HTTPException(422, "Metric scope must match the profile scope")
        items.append(
            EvaluationMetricProfileItem(
                profile_id=profile.id,
                position=position,
                key=metric.metric_type.value,
                display_name=catalog.display_name,
                criteria=catalog.description,
                weight_percent=metric.weight_percent,
                evaluation_params=list(catalog.required_fields),
                config=metric.config,
                custom_instruction=metric.custom_instruction,
            )
        )
    return items


@router.get("/metric-profiles", response_model=EvaluationMetricProfilesPublic)
async def read_metric_profiles(
    session: SessionDep,
    _user: CurrentUser,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=200),
    evaluation_mode: EvaluationMode | None = None,
    evaluation_scope: EvaluationScope | None = None,
) -> EvaluationMetricProfilesPublic:
    statement = select(EvaluationMetricProfile).order_by(
        col(EvaluationMetricProfile.updated_at).desc()
    )
    if evaluation_scope is not None:
        statement = statement.where(
            EvaluationMetricProfile.evaluation_scope == evaluation_scope.value
        )
    elif evaluation_mode is not None:
        statement = statement.where(
            EvaluationMetricProfile.evaluation_scope == evaluation_mode.value
        )
    count = int(
        (
            await session.exec(select(func.count()).select_from(statement.subquery()))
        ).one()
    )
    profiles = list((await session.exec(statement.offset(offset).limit(limit))).all())
    return EvaluationMetricProfilesPublic(
        data=[
            _metric_profile_public(
                profile, await _metric_profile_items(session, profile.id)
            )
            for profile in profiles
        ],
        count=count,
    )


@router.get("/metric-catalog", response_model=EvaluationMetricCatalogPublic)
async def read_metric_catalog(
    _user: CurrentUser, evaluation_mode: EvaluationMode | None = None
) -> EvaluationMetricCatalogPublic:
    data = [
        EvaluationMetricCatalogItem(
            metric_type=metric_type,
            display_name=definition.display_name,
            description=definition.description,
            required_fields=list(definition.required_fields),
            score_direction=definition.score_direction,
            uses_llm=definition.uses_llm,
            docs_url=definition.docs_url,
            evaluation_mode=definition.evaluation_mode,
            required_config=list(definition.required_config),
            supports_custom_instruction=definition.supports_custom_instruction,
        )
        for metric_type, definition in METRIC_CATALOG.items()
        if evaluation_mode is None or definition.evaluation_mode == evaluation_mode
    ]
    return EvaluationMetricCatalogPublic(data=data, count=len(data))


@router.post("/metric-profiles", response_model=EvaluationMetricProfilePublic)
async def create_metric_profile(
    profile_in: EvaluationMetricProfileCreate,
    session: SessionDep,
    _user: CurrentUser,
) -> EvaluationMetricProfilePublic:
    profile = EvaluationMetricProfile(**profile_in.model_dump(exclude={"metrics"}))
    session.add(profile)
    await session.flush()
    items = await _build_metric_profile_items(session, profile, profile_in.metrics)
    session.add_all(items)
    await session.commit()
    await session.refresh(profile)
    return _metric_profile_public(profile, items)


@router.put(
    "/metric-profiles/{profile_id}", response_model=EvaluationMetricProfilePublic
)
async def update_metric_profile(
    profile_id: uuid.UUID,
    profile_in: EvaluationMetricProfileUpdate,
    session: SessionDep,
    _user: CurrentUser,
) -> EvaluationMetricProfilePublic:
    profile = await session.get(EvaluationMetricProfile, profile_id)
    if not profile:
        raise HTTPException(404, "Metric profile not found")
    if (
        profile_in.expected_version is not None
        and profile_in.expected_version != profile.version
    ):
        raise HTTPException(409, "Metric profile was modified by another user")
    profile.sqlmodel_update(
        profile_in.model_dump(exclude={"metrics", "expected_version"})
    )
    profile.version += 1
    profile.updated_at = get_datetime_utc()
    await session.exec(
        delete(EvaluationMetricProfileItem).where(
            col(EvaluationMetricProfileItem.profile_id) == profile.id
        )
    )
    items = await _build_metric_profile_items(session, profile, profile_in.metrics)
    session.add(profile)
    session.add_all(items)
    await session.commit()
    await session.refresh(profile)
    return _metric_profile_public(profile, items)


async def _delete_metric_profiles(ids: list[uuid.UUID], session: SessionDep) -> None:
    profiles = list(
        (
            await session.exec(
                select(EvaluationMetricProfile).where(
                    col(EvaluationMetricProfile.id).in_(ids)
                )
            )
        ).all()
    )
    if len(profiles) != len(ids):
        raise HTTPException(404, "Metric profile not found")
    references = 0
    for model, field in (
        (EvaluationDataset, EvaluationDataset.metric_profile_id),
        (EvaluationScenario, EvaluationScenario.metric_profile_id),
        (EvaluationRun, EvaluationRun.metric_profile_id),
        (EvaluationScenarioRun, EvaluationScenarioRun.metric_profile_id),
        (EvaluationComparison, EvaluationComparison.metric_profile_id),
        (EvaluationJob, EvaluationJob.metric_profile_id),
    ):
        references += int(
            (
                await session.exec(
                    select(func.count()).select_from(model).where(col(field).in_(ids))
                )
            ).one()
        )
    if references:
        raise HTTPException(409, "Referenced metric profiles cannot be deleted")
    for profile in profiles:
        await session.delete(profile)
    await session.commit()


@router.delete("/metric-profiles/{profile_id}")
async def delete_metric_profile(
    profile_id: uuid.UUID, session: SessionDep, _user: CurrentUser
) -> Message:
    await _delete_metric_profiles([profile_id], session)
    return Message(message="Metric profile deleted successfully")


@router.post("/metric-profiles/bulk-delete")
async def bulk_delete_metric_profiles(
    request: BulkDeleteRequest, session: SessionDep, _user: CurrentUser
) -> Message:
    await _delete_metric_profiles(request.ids, session)
    return Message(message=f"Deleted {len(request.ids)} metric profiles")


@router.get("/endpoints", response_model=EvaluationEndpointsPublic)
async def read_endpoints(
    session: SessionDep,
    _user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
) -> EvaluationEndpointsPublic:
    statement = select(EvaluationEndpoint).order_by(col(EvaluationEndpoint.name))
    if not _user.is_superuser:
        statement = statement.where(EvaluationEndpoint.is_active == True)  # noqa: E712
    count = int(
        (
            await session.exec(select(func.count()).select_from(statement.subquery()))
        ).one()
    )
    endpoints = list((await session.exec(statement.offset(offset).limit(limit))).all())
    return EvaluationEndpointsPublic(
        data=[_endpoint_public(item) for item in endpoints], count=count
    )


@router.post("/endpoints", response_model=EvaluationEndpointPublic)
async def create_endpoint(
    endpoint_in: EvaluationEndpointCreate, session: SessionDep, _admin: CurrentSuperuser
) -> EvaluationEndpointPublic:
    endpoint = EvaluationEndpoint(
        **endpoint_in.model_dump(exclude={"headers", "base_url"}),
        base_url=_validate_external_url(endpoint_in.base_url),
        encrypted_headers=encrypt_evaluation_headers(endpoint_in.headers),
    )
    session.add(endpoint)
    await session.commit()
    await session.refresh(endpoint)
    return _endpoint_public(endpoint)


@router.put("/endpoints/{endpoint_id}", response_model=EvaluationEndpointPublic)
async def update_endpoint(
    endpoint_id: uuid.UUID,
    endpoint_in: EvaluationEndpointUpdate,
    session: SessionDep,
    _admin: CurrentSuperuser,
) -> EvaluationEndpointPublic:
    endpoint = await session.get(EvaluationEndpoint, endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Evaluation endpoint not found")
    updates = endpoint_in.model_dump(exclude_unset=True, exclude={"headers"})
    if "base_url" in updates:
        updates["base_url"] = _validate_external_url(updates["base_url"])
    endpoint.sqlmodel_update(updates)
    if endpoint_in.headers is not None:
        endpoint.encrypted_headers = encrypt_evaluation_headers(endpoint_in.headers)
    endpoint.updated_at = get_datetime_utc()
    session.add(endpoint)
    await session.commit()
    await session.refresh(endpoint)
    return _endpoint_public(endpoint)


@router.delete("/endpoints/{endpoint_id}")
async def disable_endpoint(
    endpoint_id: uuid.UUID, session: SessionDep, _admin: CurrentSuperuser
) -> Message:
    endpoint = await session.get(EvaluationEndpoint, endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Evaluation endpoint not found")
    endpoint.is_active = False
    endpoint.updated_at = get_datetime_utc()
    session.add(endpoint)
    await session.commit()
    return Message(message="Evaluation endpoint disabled")


@router.get("/single-turn/datasets", response_model=EvaluationDatasetsPublic)
@router.get(
    "/datasets", response_model=EvaluationDatasetsPublic, include_in_schema=False
)
async def read_datasets(
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
) -> EvaluationDatasetsPublic:
    statement = (
        select(EvaluationDataset)
        .where(EvaluationDataset.evaluation_type == "single_turn")
        .order_by(col(EvaluationDataset.updated_at).desc())
    )
    count_statement = (
        select(func.count())
        .select_from(EvaluationDataset)
        .where(EvaluationDataset.evaluation_type == "single_turn")
    )
    if not user.is_superuser:
        statement, count_statement = (
            statement.where(EvaluationDataset.owner_id == user.id),
            count_statement.where(EvaluationDataset.owner_id == user.id),
        )
    datasets = list((await session.exec(statement.offset(offset).limit(limit))).all())
    counts = list(
        (
            await session.exec(
                select(col(EvaluationDatasetRow.dataset_id), func.count())
                .where(
                    col(EvaluationDatasetRow.dataset_id).in_(
                        [item.id for item in datasets] or [uuid.UUID(int=0)]
                    )
                )
                .group_by(col(EvaluationDatasetRow.dataset_id))
            )
        ).all()
    )
    count_map = {key: int(value) for key, value in counts}
    return EvaluationDatasetsPublic(
        data=[
            _dataset_public(item, [], count_map.get(item.id, 0)) for item in datasets
        ],
        count=int((await session.exec(count_statement)).one()),
    )


@router.post("/single-turn/datasets", response_model=EvaluationDatasetPublic)
@router.post(
    "/datasets", response_model=EvaluationDatasetPublic, include_in_schema=False
)
async def create_dataset(
    dataset_in: EvaluationDatasetCreate, session: SessionDep, user: CurrentUser
) -> EvaluationDatasetPublic:
    if dataset_in.evaluator == "deepeval" and not dataset_in.metric_profile_id:
        raise HTTPException(422, "DeepEval datasets require a metric profile")
    if dataset_in.endpoint_id:
        await _endpoint_or_422(session, dataset_in.endpoint_id)
    if dataset_in.metric_profile_id:
        await _metric_profile_or_422(
            session,
            dataset_in.metric_profile_id,
            expected_mode=EvaluationMode.SINGLE_TURN,
        )
    _reject_sensitive_dataset_headers(dataset_in.headers)
    _validate_evaluator(dataset_in.evaluator)
    dataset = EvaluationDataset(
        **dataset_in.model_dump(exclude={"rows"}),
        method="POST",
        owner_id=user.id,
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    session.add(dataset)
    await session.flush()
    rows = [
        EvaluationDatasetRow(**row.model_dump(), dataset_id=dataset.id)
        for row in dataset_in.rows
    ]
    session.add_all(rows)
    await session.commit()
    await session.refresh(dataset)
    return _dataset_public(dataset, rows)


def _single_turn_document_create(
    document: SingleTurnDatasetDocument,
) -> EvaluationDatasetCreate:
    for case in document.cases:
        _reject_sensitive_dataset_headers(case.request.headers)
    return EvaluationDatasetCreate(
        name=document.name,
        description=document.description,
        evaluation_type="single_turn",
        endpoint_id=document.endpoint_id,
        metric_profile_id=document.metric_profile_id,
        headers={},
        body_template="{}",
        response_path=None,
        threshold=document.threshold,
        evaluator=document.evaluator,
        rows=[
            EvaluationDatasetRowCreate(
                input=case.input,
                expected_output=case.expected_output,
                request_headers=case.request.headers,
                request_body=json.dumps(case.request.body, ensure_ascii=False),
                response_path=case.request.actual_output_json_pointer,
            )
            for case in document.cases
        ],
    )


@router.post("/single-turn/datasets/import", response_model=EvaluationDatasetPublic)
async def import_single_turn_dataset(
    file: UploadFile, session: SessionDep, user: CurrentUser
) -> EvaluationDatasetPublic:
    content = await file.read(MAX_SAVED_DATASET_BYTES + 1)
    if len(content) > MAX_SAVED_DATASET_BYTES:
        raise HTTPException(413, "Dataset cannot exceed 100 MB")
    if not (file.filename or "").lower().endswith(".json"):
        raise HTTPException(415, "Only .json datasets are supported")
    try:
        document = SingleTurnDatasetDocument.model_validate_json(content)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid single-turn dataset JSON: {exc}")
    return await create_dataset(_single_turn_document_create(document), session, user)


@router.post(
    "/single-turn/datasets/{dataset_id}/import",
    response_model=EvaluationDatasetImportResult,
)
@router.post(
    "/datasets/{dataset_id}/import",
    response_model=EvaluationDatasetImportResult,
    include_in_schema=False,
)
async def import_dataset_rows(
    dataset_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    file: UploadFile = File(description="UTF-8 JSON dataset"),
) -> EvaluationDatasetImportResult:
    dataset = await _dataset_or_404(session, user, dataset_id)
    content = await file.read(MAX_SAVED_DATASET_BYTES + 1)
    if len(content) > MAX_SAVED_DATASET_BYTES:
        raise HTTPException(413, "Dataset cannot exceed 100 MB")
    rows = _import_rows(file.filename or "dataset.json", content)
    session.add_all(
        [
            EvaluationDatasetRow(**row.model_dump(), dataset_id=dataset.id)
            for row in rows
        ]
    )
    dataset.updated_at = get_datetime_utc()
    dataset.updated_by_id = user.id
    session.add(dataset)
    await session.commit()
    return EvaluationDatasetImportResult(
        imported=len(rows),
        row_count=await _count(
            session, EvaluationDatasetRow, EvaluationDatasetRow.dataset_id == dataset.id
        ),
    )


@router.get(
    "/single-turn/datasets/{dataset_id}", response_model=EvaluationDatasetPublic
)
@router.get(
    "/datasets/{dataset_id}",
    response_model=EvaluationDatasetPublic,
    include_in_schema=False,
)
async def read_dataset(
    dataset_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
) -> EvaluationDatasetPublic:
    dataset = await _dataset_or_404(session, user, dataset_id)
    rows = list(
        (
            await session.exec(
                select(EvaluationDatasetRow)
                .where(EvaluationDatasetRow.dataset_id == dataset.id)
                .order_by(col(EvaluationDatasetRow.created_at))
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )
    return _dataset_public(
        dataset,
        rows,
        await _count(
            session, EvaluationDatasetRow, EvaluationDatasetRow.dataset_id == dataset.id
        ),
    )


@router.get(
    "/single-turn/datasets/{dataset_id}/export",
    response_model=SingleTurnDatasetDocument,
)
async def export_single_turn_dataset(
    dataset_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Response:
    dataset = await _dataset_or_404(session, user, dataset_id)
    rows = list(
        (
            await session.exec(
                select(EvaluationDatasetRow)
                .where(EvaluationDatasetRow.dataset_id == dataset.id)
                .order_by(col(EvaluationDatasetRow.created_at))
            )
        ).all()
    )
    try:
        body = json.loads(dataset.body_template)
    except json.JSONDecodeError as exc:
        raise HTTPException(409, "Saved request body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(409, "Saved request body must be a JSON object")
    document = SingleTurnDatasetDocument(
        name=dataset.name,
        description=dataset.description,
        test_type="single_turn",
        endpoint_id=cast(uuid.UUID, dataset.endpoint_id),
        metric_profile_id=dataset.metric_profile_id,
        threshold=dataset.threshold,
        evaluator=cast(Literal["deepeval", "local"], dataset.evaluator),
        cases=[
            SingleTurnDatasetCaseDocument.model_validate(
                {
                    "input": row.input,
                    "request": EvaluationRequestDocument(
                        headers=row.request_headers or dataset.headers,
                        body=json.loads(row.request_body) if row.request_body else body,
                        actual_output_json_pointer=(
                            row.response_path
                            if row.request_body
                            else dataset.response_path
                        ),
                    ),
                    "expected_output": row.expected_output,
                }
            )
            for row in rows
        ],
    )
    return Response(
        content=document.model_dump_json(indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="single-turn-dataset-{dataset.id}.json"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put(
    "/single-turn/datasets/{dataset_id}", response_model=EvaluationDatasetPublic
)
@router.put(
    "/datasets/{dataset_id}",
    response_model=EvaluationDatasetPublic,
    include_in_schema=False,
)
async def update_dataset(
    dataset_id: uuid.UUID,
    dataset_in: EvaluationDatasetUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationDatasetPublic:
    dataset = await _dataset_or_404(session, user, dataset_id)
    next_evaluator = dataset_in.evaluator or dataset.evaluator
    next_profile_id = (
        dataset_in.metric_profile_id
        if "metric_profile_id" in dataset_in.model_fields_set
        else dataset.metric_profile_id
    )
    if next_evaluator == "deepeval" and not next_profile_id:
        raise HTTPException(422, "DeepEval datasets require a metric profile")
    if dataset_in.endpoint_id:
        await _endpoint_or_422(session, dataset_in.endpoint_id)
    if dataset_in.metric_profile_id:
        await _metric_profile_or_422(
            session,
            dataset_in.metric_profile_id,
            expected_mode=EvaluationMode.SINGLE_TURN,
        )
    if dataset_in.headers is not None:
        _reject_sensitive_dataset_headers(dataset_in.headers)
    if dataset_in.evaluator is not None:
        _validate_evaluator(dataset_in.evaluator)
    dataset.sqlmodel_update(dataset_in.model_dump(exclude_unset=True))
    dataset.updated_at = get_datetime_utc()
    dataset.updated_by_id = user.id
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return _dataset_public(
        dataset,
        [],
        await _count(
            session, EvaluationDatasetRow, EvaluationDatasetRow.dataset_id == dataset.id
        ),
    )


@router.delete("/single-turn/datasets/{dataset_id}")
@router.delete("/datasets/{dataset_id}", include_in_schema=False)
async def delete_dataset(
    dataset_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Message:
    dataset = await _dataset_or_404(session, user, dataset_id)
    await session.delete(dataset)
    await session.commit()
    return Message(message="Evaluation dataset deleted successfully")


@router.get(
    "/single-turn/datasets/{dataset_id}/rows",
    response_model=EvaluationDatasetRowsPublic,
)
async def read_dataset_rows(
    dataset_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=200),
) -> EvaluationDatasetRowsPublic:
    await _dataset_or_404(session, user, dataset_id)
    condition = EvaluationDatasetRow.dataset_id == dataset_id
    statement = (
        select(EvaluationDatasetRow)
        .where(condition)
        .order_by(col(EvaluationDatasetRow.created_at))
    )
    rows = list((await session.exec(statement.offset(offset).limit(limit))).all())
    return EvaluationDatasetRowsPublic(
        data=[EvaluationDatasetRowPublic.model_validate(row) for row in rows],
        count=await _count(session, EvaluationDatasetRow, condition),
    )


@router.post(
    "/single-turn/datasets/{dataset_id}/rows",
    response_model=EvaluationDatasetRowPublic,
)
@router.post(
    "/datasets/{dataset_id}/rows",
    response_model=EvaluationDatasetRowPublic,
    include_in_schema=False,
)
async def create_dataset_row(
    dataset_id: uuid.UUID,
    row_in: EvaluationDatasetRowCreate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationDatasetRow:
    dataset = await _dataset_or_404(session, user, dataset_id)
    _reject_sensitive_dataset_headers(row_in.request_headers or {})
    row = EvaluationDatasetRow(**row_in.model_dump(), dataset_id=dataset_id)
    session.add(row)
    dataset.updated_at = get_datetime_utc()
    dataset.updated_by_id = user.id
    session.add(dataset)
    await session.commit()
    await session.refresh(row)
    return row


@router.put(
    "/single-turn/datasets/{dataset_id}/rows/{row_id}",
    response_model=EvaluationDatasetRowPublic,
)
@router.put(
    "/datasets/{dataset_id}/rows/{row_id}",
    response_model=EvaluationDatasetRowPublic,
    include_in_schema=False,
)
async def update_dataset_row(
    dataset_id: uuid.UUID,
    row_id: uuid.UUID,
    row_in: EvaluationDatasetRowUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationDatasetRow:
    dataset = await _dataset_or_404(session, user, dataset_id)
    _reject_sensitive_dataset_headers(row_in.request_headers or {})
    row = await session.get(EvaluationDatasetRow, row_id)
    if not row or row.dataset_id != dataset_id:
        raise HTTPException(404, "Evaluation dataset row not found")
    row.sqlmodel_update(row_in.model_dump(exclude_unset=True))
    session.add(row)
    dataset.updated_at = get_datetime_utc()
    dataset.updated_by_id = user.id
    session.add(dataset)
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/single-turn/datasets/{dataset_id}/rows/{row_id}")
@router.delete("/datasets/{dataset_id}/rows/{row_id}", include_in_schema=False)
async def delete_dataset_row(
    dataset_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Message:
    dataset = await _dataset_or_404(session, user, dataset_id)
    row = await session.get(EvaluationDatasetRow, row_id)
    if not row or row.dataset_id != dataset_id:
        raise HTTPException(404, "Evaluation dataset row not found")
    await session.delete(row)
    dataset.updated_at = get_datetime_utc()
    dataset.updated_by_id = user.id
    session.add(dataset)
    await session.commit()
    return Message(message="Evaluation dataset row deleted successfully")


async def _validate_dataset_job_request(
    dataset_id: uuid.UUID,
    session: AsyncSession,
    user: User,
    baseline_run_id: uuid.UUID | None,
    metric_profile_id: uuid.UUID | None = None,
) -> None:
    dataset = await _dataset_or_404(session, user, dataset_id)
    _validate_evaluator(dataset.evaluator)
    if dataset.evaluator == "deepeval":
        selected_profile_id = metric_profile_id or dataset.metric_profile_id
        if not selected_profile_id:
            raise HTTPException(422, "DeepEval datasets require a metric profile")
        await _metric_profile_or_422(
            session, selected_profile_id, expected_mode=EvaluationMode.SINGLE_TURN
        )
    _ensure_evaluator_ready(dataset.evaluator)
    await _endpoint_or_422(session, dataset.endpoint_id)
    row_count = await _count(
        session, EvaluationDatasetRow, EvaluationDatasetRow.dataset_id == dataset_id
    )
    if not row_count:
        raise HTTPException(
            422, "Add at least one dataset row before running an evaluation"
        )
    if row_count > MAX_EXECUTION_ROWS:
        raise HTTPException(422, f"A run can contain at most {MAX_EXECUTION_ROWS} rows")
    if baseline_run_id:
        baseline = await session.get(EvaluationRun, baseline_run_id)
        if not baseline or baseline.dataset_id != dataset_id:
            raise HTTPException(422, "Baseline run must belong to this dataset")


async def _job_public(session: AsyncSession, job: EvaluationJob) -> EvaluationJobPublic:
    run_id = (
        await session.exec(
            select(EvaluationRun.id).where(EvaluationRun.job_id == job.id)
        )
    ).first()
    if not run_id:
        run_id = (
            await session.exec(
                select(EvaluationScenarioRun.id).where(
                    EvaluationScenarioRun.job_id == job.id
                )
            )
        ).first()
    return EvaluationJobPublic(**job.model_dump(), run_id=run_id)


@router.post(
    "/single-turn/datasets/{dataset_id}/run",
    response_model=EvaluationJobPublic,
    status_code=202,
)
@router.post(
    "/datasets/{dataset_id}/run",
    response_model=EvaluationJobPublic,
    status_code=202,
    include_in_schema=False,
)
async def enqueue_saved_dataset_run(
    dataset_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    baseline_run_id: uuid.UUID | None = Query(default=None),
    metric_profile_id: uuid.UUID | None = Query(default=None),
) -> EvaluationJobPublic:
    await _validate_dataset_job_request(
        dataset_id, session, user, baseline_run_id, metric_profile_id
    )
    job = await enqueue_dataset_job(
        session,
        dataset_id=dataset_id,
        owner_id=user.id,
        baseline_run_id=baseline_run_id,
        metric_profile_id=metric_profile_id,
    )
    return await _job_public(session, job)


@router.get("/jobs/{job_id}", response_model=EvaluationJobPublic)
async def read_evaluation_job(
    job_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> EvaluationJobPublic:
    job = await session.get(EvaluationJob, job_id)
    if not job or (not user.is_superuser and job.owner_id != user.id):
        raise HTTPException(404, "Evaluation job not found")
    return await _job_public(session, job)


async def _execute_saved_dataset(
    dataset_id: uuid.UUID,
    session: AsyncSession,
    user: User,
    baseline_run_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    endpoint_override_id: uuid.UUID | None = None,
    metric_profile_override_id: uuid.UUID | None = None,
    comparison_group_id: uuid.UUID | None = None,
    comparison_mode: EvaluationComparisonMode | None = None,
) -> SavedRun:
    async with _run_semaphore:
        dataset = await _dataset_or_404(session, user, dataset_id)
        _validate_evaluator(dataset.evaluator)
        metric_profile: EvaluationMetricProfile | None = None
        metric_profile_items: list[EvaluationMetricProfileItem] = []
        metric_definitions: list[EvaluationMetricDefinitionCreate] | None = None
        selected_profile_id = metric_profile_override_id or dataset.metric_profile_id
        if dataset.evaluator == "deepeval" and selected_profile_id:
            metric_profile, metric_profile_items = await _metric_profile_or_422(
                session, selected_profile_id, expected_mode=EvaluationMode.SINGLE_TURN
            )
            metric_definitions = [
                _metric_definition(item) for item in metric_profile_items
            ]
        if dataset.evaluator == "deepeval" and not metric_definitions:
            raise HTTPException(422, "DeepEval datasets require a metric profile")
        _ensure_evaluator_ready(dataset.evaluator)
        endpoint = await _endpoint_or_422(
            session, endpoint_override_id or dataset.endpoint_id
        )
        rows = list(
            (
                await session.exec(
                    select(EvaluationDatasetRow)
                    .where(EvaluationDatasetRow.dataset_id == dataset_id)
                    .order_by(col(EvaluationDatasetRow.created_at))
                )
            ).all()
        )
        if not rows:
            raise HTTPException(
                422, "Add at least one dataset row before running an evaluation"
            )
        if len(rows) > MAX_EXECUTION_ROWS:
            raise HTTPException(
                422, f"A run can contain at most {MAX_EXECUTION_ROWS} rows"
            )
        for definition in metric_definitions or []:
            if definition.custom_metric_id is None:
                continue
            for row in rows:
                try:
                    ensure_required_values(
                        [
                            key
                            for key in definition.required_keys
                            if key != "actual_output"
                        ],
                        {
                            "input": row.input,
                            "expected_output": row.expected_output,
                        },
                    )
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
        baseline_rows: list[EvaluationRunRow] = []
        if baseline_run_id:
            baseline = await session.get(EvaluationRun, baseline_run_id)
            if not baseline or baseline.dataset_id != dataset.id:
                raise HTTPException(422, "Baseline run must belong to this dataset")
            baseline_rows = list(
                (
                    await session.exec(
                        select(EvaluationRunRow).where(
                            EvaluationRunRow.run_id == baseline.id
                        )
                    )
                ).all()
            )
        run = EvaluationRun(
            dataset_id=dataset.id,
            owner_id=user.id,
            baseline_run_id=baseline_run_id,
            evaluator=dataset.evaluator,
            job_id=job_id,
            comparison_group_id=comparison_group_id,
            metric_profile_id=metric_profile.id if metric_profile else None,
            metric_profile_version=metric_profile.version if metric_profile else None,
            metric_profile_snapshot=_metric_profile_snapshot(
                metric_profile, metric_profile_items
            )
            if metric_profile
            else None,
        )
        session.add(run)
        await session.flush()
        saved: list[EvaluationRunRow] = []
        metric_results: list[EvaluationRunMetricResult] = []
        try:
            # Dataset headers were a legacy plaintext field. Credentials now
            # live exclusively on the administrator-managed endpoint.
            headers = {
                **decrypt_evaluation_headers(endpoint.encrypted_headers),
                **dataset.headers,
            }
        except Exception as exc:
            raise HTTPException(500, "Unable to read the endpoint credentials") from exc
        for index, row in enumerate(rows):
            try:
                status, response_body, actual, _ = await _call_endpoint(
                    endpoint.base_url,
                    {**headers, **(row.request_headers or {})},
                    row.request_body or dataset.body_template,
                    row.response_path if row.request_body else dataset.response_path,
                    {"input": row.input},
                )
                evaluation = (
                    await _evaluate_live_row(
                        row.input,
                        actual,
                        row.expected_output,
                        index,
                        dataset.threshold,
                        dataset.evaluator,
                        metric_definitions,
                    )
                    if comparison_mode != EvaluationComparisonMode.RELATIVE
                    else None
                )
                saved_row = EvaluationRunRow(
                    run_id=run.id,
                    dataset_row_id=row.id,
                    input=row.input,
                    expected_output=row.expected_output,
                    actual_output=actual,
                    response_status=status,
                    response_body=response_body,
                    score=evaluation.score if evaluation else None,
                    passed=evaluation.passed if evaluation else False,
                    metrics=(
                        [item.model_dump() for item in evaluation.metrics]
                        if evaluation
                        else []
                    ),
                )
                saved.append(saved_row)
                if evaluation:
                    metric_results.extend(
                        EvaluationRunMetricResult(
                            run_row_id=saved_row.id,
                            metric_key=metric.name,
                            display_name=metric.display_name or metric.name,
                            score=metric.score,
                            raw_score_ratio=metric.raw_score_ratio,
                            score_direction=metric.score_direction
                            or "higher_is_better",
                            weight_percent=metric.weight_percent,
                            weighted_score=metric.weighted_score,
                            reason=metric.reason,
                            error=metric.error,
                        )
                        for metric in evaluation.metrics
                        if metric.weight_percent is not None
                        and metric.weighted_score is not None
                    )
            except (httpx.HTTPError, ValueError) as exc:
                saved.append(
                    EvaluationRunRow(
                        run_id=run.id,
                        dataset_row_id=row.id,
                        input=row.input,
                        expected_output=row.expected_output,
                        score=(
                            None
                            if comparison_mode == EvaluationComparisonMode.RELATIVE
                            else 0
                        ),
                        error=str(exc),
                        metrics=[],
                    )
                )
        await _stage_run_evidence(session, saved, metric_results)
        run.total, run.passed = len(saved), sum(row.passed for row in saved)
        run.failed = run.total - run.passed
        run.pass_rate = round(run.passed / run.total, 4)
        scored = [row.score for row in saved if row.score is not None]
        run.average_score = round_score(sum(scored) / len(scored)) if scored else 0
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return _saved_run(run, saved, baseline_rows)


async def _arena_compare_rows(
    row_a: SavedRunRow, row_b: SavedRunRow
) -> dict[str, object]:
    from deepeval.metrics import ArenaGEval
    from deepeval.test_case import (
        ArenaTestCase,
        Contestant,
        LLMTestCase,
        SingleTurnParams,
    )

    metric = ArenaGEval(
        name="A/B 응답 비교",
        criteria="동일 입력과 기대 응답을 기준으로 더 정확하고 유용하며 안전한 응답을 고르세요. 차이가 없으면 동점으로 판정하고 이유는 한국어로 작성하세요.",
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        model=settings.DEEPEVAL_MODEL,
    )
    await metric.a_measure(
        ArenaTestCase(
            contestants=[
                Contestant(
                    name="A",
                    test_case=LLMTestCase(
                        input=row_a.input,
                        actual_output=row_a.actual_output,
                        expected_output=row_a.expected_output,
                    ),
                ),
                Contestant(
                    name="B",
                    test_case=LLMTestCase(
                        input=row_b.input,
                        actual_output=row_b.actual_output,
                        expected_output=row_b.expected_output,
                    ),
                ),
            ]
        )
    )
    winner = str(metric.winner or "tie").strip().upper()
    return {
        "winner": winner if winner in {"A", "B"} else "tie",
        "reason": ensure_korean_reason(
            str(metric.reason or "")[:2000] or None, 0, settings.DEEPEVAL_MODEL
        ),
    }


def _comparison_public(comparison: EvaluationComparison) -> EvaluationComparisonPublic:
    return EvaluationComparisonPublic.model_validate(comparison)


@router.post(
    "/single-turn/datasets/{dataset_id}/comparisons",
    response_model=EvaluationComparisonPublic,
)
async def create_single_turn_comparison(
    dataset_id: uuid.UUID,
    comparison_in: EvaluationComparisonCreate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationComparisonPublic:
    dataset = await _dataset_or_404(session, user, dataset_id)
    endpoint_a = await _endpoint_or_422(session, comparison_in.endpoint_a_id)
    endpoint_b = await _endpoint_or_422(session, comparison_in.endpoint_b_id)
    profile, items = await _metric_profile_or_422(
        session,
        comparison_in.metric_profile_id,
        expected_mode=EvaluationMode.SINGLE_TURN,
    )
    comparison = EvaluationComparison(
        owner_id=user.id,
        evaluation_mode="single_turn",
        dataset_id=dataset.id,
        endpoint_a_id=endpoint_a.id,
        endpoint_b_id=endpoint_b.id,
        metric_profile_id=profile.id,
        metric_profile_version=profile.version,
        metric_profile_snapshot=_metric_profile_snapshot(profile, items),
        comparison_mode=comparison_in.comparison_mode.value,
    )
    session.add(comparison)
    await session.commit()
    try:

        async def execute_candidate(endpoint_id: uuid.UUID) -> SavedRun:
            async with AsyncSession(
                engine, expire_on_commit=False
            ) as candidate_session:
                return await _execute_saved_dataset(
                    dataset.id,
                    candidate_session,
                    user,
                    endpoint_override_id=endpoint_id,
                    metric_profile_override_id=profile.id,
                    comparison_group_id=comparison.id,
                    comparison_mode=comparison_in.comparison_mode,
                )

        run_a, run_b = await asyncio.gather(
            execute_candidate(endpoint_a.id), execute_candidate(endpoint_b.id)
        )
        comparison.run_a_id, comparison.run_b_id = run_a.id, run_b.id
        by_dataset_row_b = {row.dataset_row_id: row for row in run_b.rows}
        results: list[dict[str, object]] = []
        for row_a in run_a.rows:
            row_b = by_dataset_row_b.get(row_a.dataset_row_id)
            if row_b is None:
                continue
            item: dict[str, object] = {
                "row_id_a": str(row_a.id),
                "row_id_b": str(row_b.id),
                "input": row_a.input,
                "score_a": row_a.score,
                "score_b": row_b.score,
                "score_delta": (
                    round_score(row_a.score - row_b.score, clamp=False)
                    if row_a.score is not None and row_b.score is not None
                    else None
                ),
            }
            if row_a.error or row_b.error:
                item.update(
                    {
                        "winner": None,
                        "excluded": comparison_in.comparison_mode
                        in {
                            EvaluationComparisonMode.RELATIVE,
                            EvaluationComparisonMode.HYBRID,
                        },
                        "reason": (
                            "한쪽 후보 실행 실패를 절대평가에서는 0점으로 보존하고 "
                            "상대평가에서는 제외했습니다."
                        ),
                    }
                )
            elif comparison_in.comparison_mode in {
                EvaluationComparisonMode.RELATIVE,
                EvaluationComparisonMode.HYBRID,
            }:
                item.update(await _arena_compare_rows(row_a, row_b))
            results.append(item)
        comparison.results = results
        comparable = [item for item in results if not item.get("excluded")]
        comparison.comparable_count = len(comparable)
        comparison.winner_a_count = sum(
            item.get("winner") == "A" for item in comparable
        )
        comparison.winner_b_count = sum(
            item.get("winner") == "B" for item in comparable
        )
        comparison.tie_count = sum(item.get("winner") == "tie" for item in comparable)
        comparison.status = "completed"
    except Exception as exc:
        comparison.status = "partial"
        comparison.results = [
            {"reason": f"외부 실행 실패로 비교가 일부만 저장되었습니다: {exc}"[:2000]}
        ]
        session.add(comparison)
        await session.commit()
        await session.refresh(comparison)
        return _comparison_public(comparison)
    session.add(comparison)
    await session.commit()
    await session.refresh(comparison)
    return _comparison_public(comparison)


@router.get(
    "/single-turn/datasets/{dataset_id}/comparisons",
    response_model=EvaluationComparisonsPublic,
)
async def read_single_turn_comparisons(
    dataset_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=200),
) -> EvaluationComparisonsPublic:
    await _dataset_or_404(session, user, dataset_id)
    condition = EvaluationComparison.dataset_id == dataset_id
    statement = (
        select(EvaluationComparison)
        .where(condition)
        .order_by(col(EvaluationComparison.created_at).desc())
    )
    data = list((await session.exec(statement.offset(offset).limit(limit))).all())
    return EvaluationComparisonsPublic(
        data=[_comparison_public(item) for item in data],
        count=await _count(session, EvaluationComparison, condition),
    )


async def _blind_conversation_pairwise(
    turns_a: list[ScenarioRunTurnPublic], turns_b: list[ScenarioRunTurnPublic]
) -> dict[str, object]:
    from deepeval.models import GPTModel

    conversations = [
        [{"user": turn.request_body, "assistant": turn.actual_output} for turn in turns]
        for turns in (turns_a, turns_b)
    ]

    async def judge(
        first: list[dict[str, str]], second: list[dict[str, str]]
    ) -> PairwiseVerdict:
        prompt = (
            "두 익명 대화 중 문맥 유지, 정확성, 유용성, 안전성이 더 나은 대화를 "
            "선택하세요. 품질 차이가 없으면 tie로 판정하고 한국어 reason을 작성하세요. "
            f"first={json.dumps(first, ensure_ascii=False)} second={json.dumps(second, ensure_ascii=False)}"
        )
        generated, _ = await GPTModel(model=settings.DEEPEVAL_MODEL).a_generate(
            prompt, schema=PairwiseVerdict
        )
        return (
            generated
            if isinstance(generated, PairwiseVerdict)
            else PairwiseVerdict.model_validate(generated)
        )

    forward, reverse = await asyncio.gather(
        judge(conversations[0], conversations[1]),
        judge(conversations[1], conversations[0]),
    )
    forward_winner = {"first": "A", "second": "B", "tie": "tie"}[forward.winner]
    reverse_winner = {"first": "B", "second": "A", "tie": "tie"}[reverse.winner]
    winner = forward_winner if forward_winner == reverse_winner else "tie"
    reason = (
        forward.reason
        if winner != "tie"
        else "후보 순서 반전 판정이 일치하지 않아 동점으로 처리했습니다."
    )
    return {
        "winner": winner,
        "reason": reason[:2000],
        "forward_winner": forward_winner,
        "reverse_winner": reverse_winner,
    }


@router.post(
    "/multi-turn/datasets/{scenario_id}/comparisons",
    response_model=EvaluationComparisonPublic,
)
async def create_multi_turn_comparison(
    scenario_id: uuid.UUID,
    comparison_in: EvaluationComparisonCreate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationComparisonPublic:
    scenario = await _scenario_or_404(session, user, scenario_id)
    endpoint_a = await _endpoint_or_422(session, comparison_in.endpoint_a_id)
    endpoint_b = await _endpoint_or_422(session, comparison_in.endpoint_b_id)
    profile, items = await _metric_profile_or_422(
        session,
        comparison_in.metric_profile_id,
        expected_mode=EvaluationMode.MULTI_TURN,
    )
    comparison = EvaluationComparison(
        owner_id=user.id,
        evaluation_mode="multi_turn",
        scenario_id=scenario.id,
        endpoint_a_id=endpoint_a.id,
        endpoint_b_id=endpoint_b.id,
        metric_profile_id=profile.id,
        metric_profile_version=profile.version,
        metric_profile_snapshot=_metric_profile_snapshot(profile, items),
        comparison_mode=comparison_in.comparison_mode.value,
    )
    session.add(comparison)
    await session.commit()
    try:

        async def execute_candidate(endpoint_id: uuid.UUID) -> ScenarioRunPublic:
            async with AsyncSession(
                engine, expire_on_commit=False
            ) as candidate_session:
                return await _execute_scenario(
                    scenario.id,
                    candidate_session,
                    user,
                    metric_profile_id=profile.id,
                    endpoint_override_id=endpoint_id,
                    comparison_group_id=comparison.id,
                    comparison_mode=comparison_in.comparison_mode,
                )

        run_a, run_b = await asyncio.gather(
            execute_candidate(endpoint_a.id), execute_candidate(endpoint_b.id)
        )
        comparison.scenario_run_a_id, comparison.scenario_run_b_id = run_a.id, run_b.id
        has_absolute_scores = comparison_in.comparison_mode in {
            EvaluationComparisonMode.ABSOLUTE,
            EvaluationComparisonMode.HYBRID,
        }
        item: dict[str, object] = {
            "score_a": run_a.overall_score if has_absolute_scores else None,
            "score_b": run_b.overall_score if has_absolute_scores else None,
            "score_delta": (
                round_score(run_a.overall_score - run_b.overall_score, clamp=False)
                if has_absolute_scores
                else None
            ),
        }
        if run_a.error or run_b.error:
            comparison.status = "partial"
            item.update(
                {
                    "winner": None,
                    "reason": "한쪽 후보가 실패하여 후속 턴과 상대평가를 중단했습니다.",
                }
            )
        elif comparison_in.comparison_mode in {
            EvaluationComparisonMode.RELATIVE,
            EvaluationComparisonMode.HYBRID,
        }:
            item.update(await _blind_conversation_pairwise(run_a.turns, run_b.turns))
            comparison.status = "completed"
        else:
            comparison.status = "completed"
        comparison.results = [item]
        comparison.comparable_count = int(not run_a.error and not run_b.error)
        comparison.winner_a_count = int(item.get("winner") == "A")
        comparison.winner_b_count = int(item.get("winner") == "B")
        comparison.tie_count = int(item.get("winner") == "tie")
    except Exception as exc:
        comparison.status = "partial"
        comparison.results = [
            {"reason": f"외부 실행 실패로 비교가 일부만 저장되었습니다: {exc}"[:2000]}
        ]
        session.add(comparison)
        await session.commit()
        await session.refresh(comparison)
        return _comparison_public(comparison)
    session.add(comparison)
    await session.commit()
    await session.refresh(comparison)
    return _comparison_public(comparison)


@router.get(
    "/multi-turn/datasets/{scenario_id}/comparisons",
    response_model=EvaluationComparisonsPublic,
)
async def read_multi_turn_comparisons(
    scenario_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=200),
) -> EvaluationComparisonsPublic:
    await _scenario_or_404(session, user, scenario_id)
    condition = EvaluationComparison.scenario_id == scenario_id
    statement = (
        select(EvaluationComparison)
        .where(condition)
        .order_by(col(EvaluationComparison.created_at).desc())
    )
    data = list((await session.exec(statement.offset(offset).limit(limit))).all())
    return EvaluationComparisonsPublic(
        data=[_comparison_public(item) for item in data],
        count=await _count(session, EvaluationComparison, condition),
    )


@router.get("/comparisons/{comparison_id}", response_model=EvaluationComparisonPublic)
async def read_comparison(
    comparison_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> EvaluationComparisonPublic:
    comparison = await session.get(EvaluationComparison, comparison_id)
    if not comparison or (not user.is_superuser and comparison.owner_id != user.id):
        raise HTTPException(404, "Evaluation comparison not found")
    return _comparison_public(comparison)


@router.delete("/comparisons/{comparison_id}")
async def delete_comparison(
    comparison_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Message:
    comparison = await session.get(EvaluationComparison, comparison_id)
    if not comparison or (not user.is_superuser and comparison.owner_id != user.id):
        raise HTTPException(404, "Evaluation comparison not found")
    await session.delete(comparison)
    await session.commit()
    return Message(message="Evaluation comparison deleted successfully")


@router.get("/comparisons/{comparison_id}/report")
async def download_comparison_report(
    comparison_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> HTMLResponse:
    comparison = await session.get(EvaluationComparison, comparison_id)
    if not comparison or (not user.is_superuser and comparison.owner_id != user.id):
        raise HTTPException(404, "Evaluation comparison not found")

    target = (
        await session.get(EvaluationDataset, comparison.dataset_id)
        if comparison.dataset_id
        else await session.get(EvaluationScenario, comparison.scenario_id)
    )

    def escaped(value: object | None) -> str:
        return html.escape("" if value is None else str(value), quote=True)

    def required_keys(item: dict[Any, Any]) -> str:
        value = item.get("required_keys")
        return ", ".join(str(key) for key in value) if isinstance(value, list) else "-"

    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{escaped(item.get(key))}</td>"
            for key in (
                "input",
                "score_a",
                "score_b",
                "score_delta",
                "winner",
                "reason",
            )
        )
        + "</tr>"
        for item in comparison.results
    )
    snapshot = comparison.metric_profile_snapshot or {}
    raw_profile_metrics = snapshot.get("metrics") if isinstance(snapshot, dict) else []
    profile_metrics = (
        raw_profile_metrics if isinstance(raw_profile_metrics, list) else []
    )
    profile_rows = "".join(
        "<tr>"
        f"<td>{escaped(item.get('display_name') or item.get('metric_type'))}</td>"
        f"<td>{escaped(item.get('weight_percent'))}%</td>"
        f"<td>{escaped(item.get('custom_metric_id') or '-')}</td>"
        f"<td>{escaped(item.get('custom_metric_version') or '-')}</td>"
        f"<td>{escaped(required_keys(item))}</td>"
        f"<td>{escaped(item.get('custom_metric_prompt') or '-')}</td>"
        "</tr>"
        for item in profile_metrics
        if isinstance(item, dict)
    )
    threshold = float(target.threshold) if target is not None else 0
    report = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>A/B 비교 평가 리포트</title><style>body{{font-family:system-ui;margin:32px;color:#222}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px;text-align:left;vertical-align:top;white-space:pre-wrap}}.cards{{display:flex;gap:16px;margin:20px 0;flex-wrap:wrap}}.card{{border:1px solid #ddd;padding:12px}}</style></head><body><h1>A/B 비교 평가 리포트</h1><p>상태 {escaped(comparison.status)} · 모드 {escaped(comparison.comparison_mode)} · 범위 {escaped(snapshot.get("evaluation_scope") if isinstance(snapshot, dict) else "-")} · 프로필 v{escaped(comparison.metric_profile_version or "-")} · 임계값 {threshold:.3f}점</p><p>절대점수 총점 = Σ(메트릭 0~100 점수 × 가중치 / 100). 상대평가 전용 모드는 임의의 절대점수를 만들지 않습니다.</p><div class="cards"><div class="card">비교 가능 {comparison.comparable_count}</div><div class="card">A 승 {comparison.winner_a_count}</div><div class="card">B 승 {comparison.winner_b_count}</div><div class="card">동점 {comparison.tie_count}</div></div><h2>프로필 스냅샷</h2><table><thead><tr><th>지표</th><th>가중치</th><th>CustomMetric ID</th><th>버전</th><th>필요 키</th><th>프롬프트</th></tr></thead><tbody>{profile_rows or '<tr><td colspan="6">스냅샷 없음</td></tr>'}</tbody></table><h2>비교 결과</h2><table><thead><tr><th>입력</th><th>A 점수</th><th>B 점수</th><th>차이</th><th>승자</th><th>한국어 사유</th></tr></thead><tbody>{rows}</tbody></table></body></html>"""
    return HTMLResponse(
        content=report,
        headers={
            "Content-Disposition": f'attachment; filename="comparison-report-{comparison.id}.html"',
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def execute_saved_dataset_job(job: EvaluationJob) -> uuid.UUID:
    if job.dataset_id is None:
        raise ValueError("Dataset evaluation job has no dataset target")
    async with AsyncSession(engine, expire_on_commit=False) as session:
        existing_run_id = (
            await session.exec(
                select(EvaluationRun.id).where(EvaluationRun.job_id == job.id)
            )
        ).first()
        if existing_run_id:
            return existing_run_id
        user = await session.get(User, job.owner_id)
        if not user:
            raise ValueError("Evaluation job owner no longer exists")
        result = await _execute_saved_dataset(
            job.dataset_id,
            session,
            user,
            baseline_run_id=job.baseline_run_id,
            job_id=job.id,
            metric_profile_override_id=job.metric_profile_id,
        )
        return result.id


async def _schedule_or_404(
    session: SessionDep, user: CurrentUser, schedule_id: uuid.UUID
) -> EvaluationSchedule:
    schedule = await session.get(EvaluationSchedule, schedule_id)
    if not schedule:
        raise HTTPException(404, "Evaluation schedule not found")
    if not user.is_superuser and schedule.owner_id != user.id:
        raise HTTPException(403, "Not enough permissions")
    return schedule


def _schedule_public(
    schedule: EvaluationSchedule,
    target: EvaluationDataset | EvaluationScenario,
    owner: User | None,
) -> EvaluationSchedulePublic:
    target_type = (
        EvaluationScheduleTargetType.SINGLE_TURN
        if schedule.dataset_id
        else EvaluationScheduleTargetType.MULTI_TURN
    )
    return EvaluationSchedulePublic(
        **schedule.model_dump(exclude={"schedule_type"}),
        schedule_type=EvaluationScheduleType(schedule.schedule_type),
        target_type=target_type,
        target_id=target.id,
        target_name=target.name,
        target_description=target.description,
        owner_name=(owner.full_name or owner.email) if owner else None,
    )


async def _schedule_target(
    session: SessionDep, schedule: EvaluationSchedule
) -> EvaluationDataset | EvaluationScenario:
    target = (
        await session.get(EvaluationDataset, schedule.dataset_id)
        if schedule.dataset_id
        else await session.get(EvaluationScenario, schedule.scenario_id)
    )
    if not target:
        raise HTTPException(404, "Evaluation schedule target not found")
    return target


async def _validate_scenario_job_request(
    scenario_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    baseline_run_id: uuid.UUID | None = None,
) -> EvaluationScenario:
    scenario = await _scenario_or_404(session, user, scenario_id)
    _validate_evaluator(scenario.evaluator)
    if scenario.evaluator == "deepeval":
        if scenario.metric_profile_id is None:
            raise HTTPException(
                422, "DeepEval multi-turn datasets require a metric profile"
            )
        await _metric_profile_or_422(
            session,
            scenario.metric_profile_id,
            expected_scope=EvaluationScope.MULTI_TURN,
        )
    _ensure_evaluator_ready(scenario.evaluator)
    await _endpoint_or_422(session, scenario.endpoint_id)
    turn_count = await _count(
        session,
        EvaluationScenarioTurn,
        EvaluationScenarioTurn.scenario_id == scenario_id,
    )
    if not turn_count:
        raise HTTPException(422, "Add at least one turn before scheduling a scenario")
    if baseline_run_id:
        baseline = await session.get(EvaluationScenarioRun, baseline_run_id)
        if not baseline or baseline.scenario_id != scenario_id:
            raise HTTPException(422, "Baseline run must belong to this scenario")
    return scenario


def _next_schedule_run(
    schedule_type: EvaluationScheduleType,
    cron_expression: str | None,
    timezone: str,
    requested: Any = None,
) -> Any:
    if schedule_type == EvaluationScheduleType.CRON:
        try:
            return next_cron_run(cron_expression or "", get_datetime_utc(), timezone)
        except CronExpressionError as exc:
            raise HTTPException(422, str(exc)) from exc
    return requested or get_datetime_utc()


@router.get("/schedules", response_model=EvaluationSchedulesPublic)
async def read_all_evaluation_schedules(
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
) -> EvaluationSchedulesPublic:
    statement = select(EvaluationSchedule).order_by(
        col(EvaluationSchedule.created_at).desc()
    )
    count_statement = select(func.count()).select_from(EvaluationSchedule)
    if not user.is_superuser:
        statement = statement.where(EvaluationSchedule.owner_id == user.id)
        count_statement = count_statement.where(EvaluationSchedule.owner_id == user.id)
    schedules = list((await session.exec(statement.offset(offset).limit(limit))).all())
    dataset_ids = {item.dataset_id for item in schedules if item.dataset_id}
    scenario_ids = {item.scenario_id for item in schedules if item.scenario_id}
    owner_ids = {item.owner_id for item in schedules}
    datasets = {
        item.id: item
        for item in (
            await session.exec(
                select(EvaluationDataset).where(
                    col(EvaluationDataset.id).in_(dataset_ids or {uuid.UUID(int=0)})
                )
            )
        ).all()
    }
    scenarios = {
        item.id: item
        for item in (
            await session.exec(
                select(EvaluationScenario).where(
                    col(EvaluationScenario.id).in_(scenario_ids or {uuid.UUID(int=0)})
                )
            )
        ).all()
    }
    owners = {
        item.id: item
        for item in (
            await session.exec(
                select(User).where(col(User.id).in_(owner_ids or {uuid.UUID(int=0)}))
            )
        ).all()
    }
    return EvaluationSchedulesPublic(
        data=[
            _schedule_public(
                schedule,
                datasets[schedule.dataset_id]
                if schedule.dataset_id
                else scenarios[cast(uuid.UUID, schedule.scenario_id)],
                owners.get(schedule.owner_id),
            )
            for schedule in schedules
        ],
        count=int((await session.exec(count_statement)).one()),
    )


@router.post("/schedules", response_model=EvaluationSchedulePublic, status_code=201)
async def create_global_evaluation_schedule(
    schedule_in: EvaluationScheduleCreate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationSchedulePublic:
    if schedule_in.target_type == EvaluationScheduleTargetType.SINGLE_TURN:
        await _validate_dataset_job_request(
            schedule_in.target_id, session, user, schedule_in.baseline_run_id
        )
        target: EvaluationDataset | EvaluationScenario = await _dataset_or_404(
            session, user, schedule_in.target_id
        )
        dataset_id, scenario_id = target.id, None
    else:
        if schedule_in.baseline_run_id:
            raise HTTPException(
                422, "Scheduled multi-turn runs do not support a baseline"
            )
        target = await _validate_scenario_job_request(
            schedule_in.target_id, session, user
        )
        dataset_id, scenario_id = None, target.id
    schedule = EvaluationSchedule(
        **schedule_in.model_dump(exclude={"target_type", "target_id", "next_run_at"}),
        dataset_id=dataset_id,
        scenario_id=scenario_id,
        owner_id=user.id,
        next_run_at=_next_schedule_run(
            schedule_in.schedule_type,
            schedule_in.cron_expression,
            schedule_in.timezone,
            schedule_in.next_run_at,
        ),
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return _schedule_public(schedule, target, user)


@router.put("/schedules/{schedule_id}", response_model=EvaluationSchedulePublic)
async def update_global_evaluation_schedule(
    schedule_id: uuid.UUID,
    schedule_in: EvaluationScheduleUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationSchedulePublic:
    schedule = await _schedule_or_404(session, user, schedule_id)
    updates = schedule_in.model_dump(exclude_unset=True)
    configuration = EvaluationScheduleBase.model_validate(
        {
            "name": updates.get("name", schedule.name),
            "schedule_type": updates.get("schedule_type", schedule.schedule_type),
            "interval_seconds": updates.get(
                "interval_seconds", schedule.interval_seconds
            ),
            "cron_expression": updates.get("cron_expression", schedule.cron_expression),
            "timezone": updates.get("timezone", schedule.timezone),
            "is_active": updates.get("is_active", schedule.is_active),
        }
    )
    if "baseline_run_id" in updates and schedule.dataset_id:
        await _validate_dataset_job_request(
            schedule.dataset_id, session, user, updates["baseline_run_id"]
        )
    if schedule.scenario_id and updates.get("baseline_run_id"):
        raise HTTPException(422, "Scheduled multi-turn runs do not support a baseline")
    schedule.sqlmodel_update(configuration.model_dump())
    if "baseline_run_id" in updates:
        schedule.baseline_run_id = updates["baseline_run_id"]
    if configuration.schedule_type == EvaluationScheduleType.CRON or any(
        key in updates for key in {"schedule_type", "cron_expression", "timezone"}
    ):
        schedule.next_run_at = _next_schedule_run(
            configuration.schedule_type,
            configuration.cron_expression,
            configuration.timezone,
            updates.get("next_run_at", schedule.next_run_at),
        )
    elif "next_run_at" in updates and updates["next_run_at"] is not None:
        schedule.next_run_at = updates["next_run_at"]
    schedule.updated_at = get_datetime_utc()
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return _schedule_public(
        schedule,
        await _schedule_target(session, schedule),
        await session.get(User, schedule.owner_id),
    )


@router.delete("/schedules/{schedule_id}")
async def delete_global_evaluation_schedule(
    schedule_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Message:
    schedule = await _schedule_or_404(session, user, schedule_id)
    await session.delete(schedule)
    await session.commit()
    return Message(message="Evaluation schedule deleted successfully")


@router.get(
    "/single-turn/datasets/{dataset_id}/schedules",
    response_model=EvaluationSchedulesPublic,
)
@router.get(
    "/datasets/{dataset_id}/schedules",
    response_model=EvaluationSchedulesPublic,
    include_in_schema=False,
)
async def read_evaluation_schedules(
    dataset_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
) -> EvaluationSchedulesPublic:
    dataset = await _dataset_or_404(session, user, dataset_id)
    statement = (
        select(EvaluationSchedule)
        .where(EvaluationSchedule.dataset_id == dataset_id)
        .order_by(col(EvaluationSchedule.created_at).desc())
    )
    if not user.is_superuser:
        statement = statement.where(EvaluationSchedule.owner_id == user.id)
    schedules = list((await session.exec(statement.offset(offset).limit(limit))).all())
    owners = {
        item.id: item
        for item in (
            await session.exec(
                select(User).where(
                    col(User.id).in_(
                        {item.owner_id for item in schedules} or {uuid.UUID(int=0)}
                    )
                )
            )
        ).all()
    }
    return EvaluationSchedulesPublic(
        data=[
            _schedule_public(item, dataset, owners.get(item.owner_id))
            for item in schedules
        ],
        count=await _count(
            session,
            EvaluationSchedule,
            EvaluationSchedule.dataset_id == dataset_id,
        ),
    )


@router.post(
    "/single-turn/datasets/{dataset_id}/schedules",
    response_model=EvaluationSchedulePublic,
    status_code=201,
)
@router.post(
    "/datasets/{dataset_id}/schedules",
    response_model=EvaluationSchedulePublic,
    status_code=201,
    include_in_schema=False,
)
async def create_evaluation_schedule(
    dataset_id: uuid.UUID,
    schedule_in: EvaluationDatasetScheduleCreate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationSchedulePublic:
    await _validate_dataset_job_request(
        dataset_id, session, user, schedule_in.baseline_run_id
    )
    schedule = EvaluationSchedule(
        **schedule_in.model_dump(exclude={"next_run_at"}),
        dataset_id=dataset_id,
        owner_id=user.id,
        next_run_at=_next_schedule_run(
            schedule_in.schedule_type,
            schedule_in.cron_expression,
            schedule_in.timezone,
            schedule_in.next_run_at,
        ),
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return _schedule_public(
        schedule, await _dataset_or_404(session, user, dataset_id), user
    )


@router.put(
    "/single-turn/datasets/{dataset_id}/schedules/{schedule_id}",
    response_model=EvaluationSchedulePublic,
)
@router.put(
    "/datasets/{dataset_id}/schedules/{schedule_id}",
    response_model=EvaluationSchedulePublic,
    include_in_schema=False,
)
async def update_evaluation_schedule(
    dataset_id: uuid.UUID,
    schedule_id: uuid.UUID,
    schedule_in: EvaluationScheduleUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationSchedulePublic:
    await _dataset_or_404(session, user, dataset_id)
    schedule = await _schedule_or_404(session, user, schedule_id)
    if schedule.dataset_id != dataset_id:
        raise HTTPException(404, "Evaluation schedule not found")
    return await update_global_evaluation_schedule(
        schedule_id, schedule_in, session, user
    )


@router.delete("/single-turn/datasets/{dataset_id}/schedules/{schedule_id}")
@router.delete(
    "/datasets/{dataset_id}/schedules/{schedule_id}", include_in_schema=False
)
async def delete_evaluation_schedule(
    dataset_id: uuid.UUID,
    schedule_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> Message:
    await _dataset_or_404(session, user, dataset_id)
    schedule = await _schedule_or_404(session, user, schedule_id)
    if schedule.dataset_id != dataset_id:
        raise HTTPException(404, "Evaluation schedule not found")
    return await delete_global_evaluation_schedule(schedule_id, session, user)


@router.get("/single-turn/datasets/{dataset_id}/runs", response_model=SavedRunsPublic)
@router.get(
    "/datasets/{dataset_id}/runs",
    response_model=SavedRunsPublic,
    include_in_schema=False,
)
async def read_saved_runs(
    dataset_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
) -> SavedRunsPublic:
    dataset = await _dataset_or_404(session, user, dataset_id)
    runs = list(
        (
            await session.exec(
                select(EvaluationRun)
                .where(
                    EvaluationRun.dataset_id == dataset_id,
                    col(EvaluationRun.comparison_group_id).is_(None),
                )
                .order_by(col(EvaluationRun.created_at).desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )
    executors = {
        executor.id: executor
        for executor in (
            await session.exec(
                select(User).where(col(User.id).in_({run.owner_id for run in runs}))
            )
        ).all()
    }
    return SavedRunsPublic(
        data=[_run_summary(run, dataset, executors.get(run.owner_id)) for run in runs],
        count=await _count(
            session,
            EvaluationRun,
            EvaluationRun.dataset_id == dataset_id,
            col(EvaluationRun.comparison_group_id).is_(None),
        ),
    )


@router.get("/single-turn/datasets/{dataset_id}/runs/{run_id}", response_model=SavedRun)
@router.get(
    "/datasets/{dataset_id}/runs/{run_id}",
    response_model=SavedRun,
    include_in_schema=False,
)
async def read_saved_run(
    dataset_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
) -> SavedRun:
    dataset = await _dataset_or_404(session, user, dataset_id)
    run = await session.get(EvaluationRun, run_id)
    if not run or run.dataset_id != dataset_id:
        raise HTTPException(404, "Evaluation run not found")
    rows = list(
        (
            await session.exec(
                select(EvaluationRunRow)
                .where(EvaluationRunRow.run_id == run.id)
                .order_by(col(EvaluationRunRow.id))
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )
    baseline_rows: list[EvaluationRunRow] = []
    if run.baseline_run_id:
        baseline_rows = list(
            (
                await session.exec(
                    select(EvaluationRunRow).where(
                        EvaluationRunRow.run_id == run.baseline_run_id
                    )
                )
            ).all()
        )
    executor = await session.get(User, run.owner_id)
    result = _saved_run(run, rows, baseline_rows, dataset, executor)
    result.row_count = await _count(
        session, EvaluationRunRow, EvaluationRunRow.run_id == run.id
    )
    return result


@router.get(
    "/single-turn/datasets/{dataset_id}/runs/{run_id}/report.html",
    response_class=HTMLResponse,
)
@router.get(
    "/datasets/{dataset_id}/runs/{run_id}/report.html",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def download_saved_run_report(
    dataset_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> HTMLResponse:
    dataset = await _dataset_or_404(session, user, dataset_id)
    run = await session.get(EvaluationRun, run_id)
    if not run or run.dataset_id != dataset_id:
        raise HTTPException(404, "Evaluation run not found")
    executor = await session.get(User, run.owner_id)
    if not executor:
        raise HTTPException(404, "Evaluation run executor not found")
    rows = list(
        (
            await session.exec(
                select(EvaluationRunRow)
                .where(EvaluationRunRow.run_id == run.id)
                .order_by(col(EvaluationRunRow.id))
            )
        ).all()
    )
    report = _html_report(
        _saved_run(run, rows, dataset=dataset, executor=executor),
        dataset,
        executor,
        run.metric_profile_snapshot,
    )
    return HTMLResponse(
        content=report,
        headers={
            "Content-Disposition": (
                f'attachment; filename="evaluation-report-{run.id}.html"'
            ),
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


def _scenario_turns(
    scenario_id: uuid.UUID,
    turns: list[EvaluationScenarioTurnCreate],
    endpoint: EvaluationEndpoint,
) -> list[EvaluationScenarioTurn]:
    identifiers = [turn.identifier for turn in turns]
    if len(set(identifiers)) != len(identifiers):
        raise HTTPException(422, "Each scenario turn identifier must be unique")
    for index, turn in enumerate(turns):
        try:
            body = json.loads(turn.body_template)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                422, f"Turn {index + 1} request body must be valid JSON"
            ) from exc
        if not isinstance(body, dict):
            raise HTTPException(
                422, f"Turn {index + 1} request body must be a JSON object"
            )
    return [
        EvaluationScenarioTurn(
            scenario_id=scenario_id,
            position=index,
            identifier=turn.identifier,
            url=_relative_turn_url(endpoint, turn.url),
            method="POST",
            encrypted_headers=encrypt_evaluation_headers(turn.headers),
            body_template=turn.body_template,
            response_path=turn.response_path,
            expected_output=turn.expected_output,
        )
        for index, turn in enumerate(turns)
    ]


def _reject_sensitive_turn_headers(
    turns: list[EvaluationScenarioTurnCreate], user: CurrentUser
) -> None:
    if user.is_superuser:
        return
    sensitive = {"authorization", "cookie", "set-cookie", "x-api-key", "api-key"}
    for turn in turns:
        if any(
            key.lower() in sensitive
            or "token" in key.lower()
            or "secret" in key.lower()
            for key in turn.headers
        ):
            raise HTTPException(
                403, "Only administrators may set authentication headers"
            )


@router.get("/multi-turn/datasets", response_model=EvaluationScenariosPublic)
@router.get(
    "/scenarios", response_model=EvaluationScenariosPublic, include_in_schema=False
)
async def read_scenarios(
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
) -> EvaluationScenariosPublic:
    statement, count_statement = (
        select(EvaluationScenario).order_by(col(EvaluationScenario.updated_at).desc()),
        select(func.count()).select_from(EvaluationScenario),
    )
    if not user.is_superuser:
        statement, count_statement = (
            statement.where(EvaluationScenario.owner_id == user.id),
            count_statement.where(EvaluationScenario.owner_id == user.id),
        )
    scenarios = list((await session.exec(statement.offset(offset).limit(limit))).all())
    turn_counts = list(
        (
            await session.exec(
                select(
                    col(EvaluationScenarioTurn.scenario_id),
                    func.count(),
                )
                .where(
                    col(EvaluationScenarioTurn.scenario_id).in_(
                        [item.id for item in scenarios] or [uuid.UUID(int=0)]
                    )
                )
                .group_by(col(EvaluationScenarioTurn.scenario_id))
            )
        ).all()
    )
    counts = {key: int(value) for key, value in turn_counts}
    return EvaluationScenariosPublic(
        data=[_scenario_public(item, [], counts.get(item.id, 0)) for item in scenarios],
        count=int((await session.exec(count_statement)).one()),
    )


@router.post("/multi-turn/datasets", response_model=EvaluationScenarioPublic)
@router.post(
    "/scenarios", response_model=EvaluationScenarioPublic, include_in_schema=False
)
async def create_scenario(
    scenario_in: EvaluationScenarioCreate, session: SessionDep, user: CurrentUser
) -> EvaluationScenarioPublic:
    endpoint = await _endpoint_or_422(session, scenario_in.endpoint_id)
    _validate_evaluator(scenario_in.evaluator)
    if scenario_in.evaluator == "deepeval" and not scenario_in.metric_profile_id:
        raise HTTPException(
            422, "DeepEval multi-turn datasets require a metric profile"
        )
    if scenario_in.metric_profile_id:
        await _metric_profile_or_422(
            session,
            scenario_in.metric_profile_id,
            expected_mode=EvaluationMode.MULTI_TURN,
        )
    _reject_sensitive_turn_headers(scenario_in.turns, user)
    scenario = EvaluationScenario(
        **scenario_in.model_dump(exclude={"turns", "endpoint_id", "test_type"}),
        endpoint_id=endpoint.id,
        owner_id=user.id,
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    session.add(scenario)
    await session.flush()
    turns = _scenario_turns(scenario.id, scenario_in.turns, endpoint)
    session.add_all(turns)
    await session.commit()
    await session.refresh(scenario)
    return _scenario_public(scenario, turns)


def _multi_turn_document_create(
    document: MultiTurnDatasetDocument,
) -> EvaluationScenarioCreate:
    return EvaluationScenarioCreate(
        name=document.name,
        description=document.description,
        endpoint_id=document.endpoint_id,
        threshold=document.threshold,
        metric_profile_id=document.metric_profile_id,
        evaluator=document.evaluator,
        turns=[
            EvaluationScenarioTurnCreate(
                identifier=case.identifier,
                url=case.request.url,
                headers=case.request.headers,
                body_template=json.dumps(case.request.body, ensure_ascii=False),
                response_path=case.request.actual_output_json_pointer,
                expected_output=case.expected_output,
            )
            for case in document.cases
        ],
    )


@router.post("/multi-turn/datasets/import", response_model=EvaluationScenarioPublic)
@router.post(
    "/scenarios/import",
    response_model=EvaluationScenarioPublic,
    include_in_schema=False,
)
async def import_scenario(
    file: UploadFile, session: SessionDep, user: CurrentUser
) -> EvaluationScenarioPublic:
    content = await file.read(MAX_DATASET_BYTES + 1)
    if len(content) > MAX_DATASET_BYTES:
        raise HTTPException(413, "Scenario cannot exceed 5 MB")
    try:
        document = MultiTurnDatasetDocument.model_validate_json(content)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid multi-turn dataset JSON: {exc}")
    return await create_scenario(_multi_turn_document_create(document), session, user)


@router.get(
    "/multi-turn/datasets/{scenario_id}", response_model=EvaluationScenarioPublic
)
@router.get(
    "/scenarios/{scenario_id}",
    response_model=EvaluationScenarioPublic,
    include_in_schema=False,
)
async def read_scenario(
    scenario_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> EvaluationScenarioPublic:
    scenario = await _scenario_or_404(session, user, scenario_id)
    turns = list(
        (
            await session.exec(
                select(EvaluationScenarioTurn)
                .where(EvaluationScenarioTurn.scenario_id == scenario.id)
                .order_by(col(EvaluationScenarioTurn.position))
            )
        ).all()
    )
    return _scenario_public(scenario, turns)


@router.get(
    "/multi-turn/datasets/{scenario_id}/export",
    response_model=MultiTurnDatasetDocument,
)
async def export_multi_turn_dataset(
    scenario_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Response:
    scenario = await _scenario_or_404(session, user, scenario_id)
    turns = list(
        (
            await session.exec(
                select(EvaluationScenarioTurn)
                .where(EvaluationScenarioTurn.scenario_id == scenario.id)
                .order_by(col(EvaluationScenarioTurn.position))
            )
        ).all()
    )
    cases: list[dict[str, Any]] = []
    for turn in turns:
        try:
            body = json.loads(turn.body_template)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                409, "Saved turn request body is not valid JSON"
            ) from exc
        if not isinstance(body, dict):
            raise HTTPException(409, "Saved turn request body must be a JSON object")
        cases.append(
            {
                "identifier": turn.identifier,
                "request": {
                    "url": turn.url,
                    # Stored header values are intentionally never exported.
                    "headers": {},
                    "body": body,
                    "actual_output_json_pointer": turn.response_path,
                },
                "expected_output": turn.expected_output,
            }
        )
    document = MultiTurnDatasetDocument(
        name=scenario.name,
        description=scenario.description,
        test_type="multi_turn",
        endpoint_id=scenario.endpoint_id,
        threshold=scenario.threshold,
        metric_profile_id=scenario.metric_profile_id,
        evaluator=cast(Literal["deepeval", "local"], scenario.evaluator),
        cases=[MultiTurnDatasetCaseDocument.model_validate(case) for case in cases],
    )
    return Response(
        content=document.model_dump_json(indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="multi-turn-dataset-{scenario.id}.json"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put(
    "/multi-turn/datasets/{scenario_id}", response_model=EvaluationScenarioPublic
)
@router.put(
    "/scenarios/{scenario_id}",
    response_model=EvaluationScenarioPublic,
    include_in_schema=False,
)
async def update_scenario(
    scenario_id: uuid.UUID,
    scenario_in: EvaluationScenarioUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationScenarioPublic:
    scenario = await _scenario_or_404(session, user, scenario_id)
    endpoint_id = scenario_in.endpoint_id or scenario.endpoint_id
    endpoint = await _endpoint_or_422(session, endpoint_id)
    if scenario_in.evaluator is not None:
        _validate_evaluator(scenario_in.evaluator)
    next_evaluator = scenario_in.evaluator or scenario.evaluator
    next_profile_id = (
        scenario_in.metric_profile_id
        if "metric_profile_id" in scenario_in.model_fields_set
        else scenario.metric_profile_id
    )
    if next_evaluator == "deepeval" and not next_profile_id:
        raise HTTPException(
            422, "DeepEval multi-turn datasets require a metric profile"
        )
    if next_profile_id:
        await _metric_profile_or_422(
            session, next_profile_id, expected_mode=EvaluationMode.MULTI_TURN
        )
    if scenario_in.turns is not None:
        _reject_sensitive_turn_headers(scenario_in.turns, user)
    scenario.sqlmodel_update(
        scenario_in.model_dump(exclude_unset=True, exclude={"turns"})
    )
    scenario.updated_at = get_datetime_utc()
    scenario.updated_by_id = user.id
    if scenario_in.turns is not None:
        existing = list(
            (
                await session.exec(
                    select(EvaluationScenarioTurn).where(
                        EvaluationScenarioTurn.scenario_id == scenario.id
                    )
                )
            ).all()
        )
        for turn in existing:
            await session.delete(turn)
        turns = _scenario_turns(scenario.id, scenario_in.turns, endpoint)
        existing_by_position = {turn.position: turn for turn in existing}
        for turn, turn_input in zip(turns, scenario_in.turns, strict=True):
            previous = existing_by_position.get(turn.position)
            if previous and not turn_input.headers:
                turn.encrypted_headers = previous.encrypted_headers
        session.add_all(turns)
    else:
        turns = list(
            (
                await session.exec(
                    select(EvaluationScenarioTurn)
                    .where(EvaluationScenarioTurn.scenario_id == scenario.id)
                    .order_by(col(EvaluationScenarioTurn.position))
                )
            ).all()
        )
    session.add(scenario)
    await session.commit()
    await session.refresh(scenario)
    return _scenario_public(scenario, turns)


@router.delete("/multi-turn/datasets/{scenario_id}")
@router.delete("/scenarios/{scenario_id}", include_in_schema=False)
async def delete_scenario(
    scenario_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Message:
    scenario = await _scenario_or_404(session, user, scenario_id)
    await session.delete(scenario)
    await session.commit()
    return Message(message="Evaluation scenario deleted successfully")


@router.post("/multi-turn/datasets/{scenario_id}/run", response_model=ScenarioRunPublic)
@router.post(
    "/scenarios/{scenario_id}/run",
    response_model=ScenarioRunPublic,
    include_in_schema=False,
)
async def run_scenario(
    scenario_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    baseline_run_id: uuid.UUID | None = Query(default=None),
    metric_profile_id: uuid.UUID | None = Query(default=None),
) -> ScenarioRunPublic:
    return await _execute_scenario(
        scenario_id,
        session,
        user,
        baseline_run_id=baseline_run_id,
        metric_profile_id=metric_profile_id,
    )


async def _execute_scenario(
    scenario_id: uuid.UUID,
    session: AsyncSession,
    user: User,
    baseline_run_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    metric_profile_id: uuid.UUID | None = None,
    endpoint_override_id: uuid.UUID | None = None,
    comparison_group_id: uuid.UUID | None = None,
    comparison_mode: EvaluationComparisonMode | None = None,
) -> ScenarioRunPublic:
    async with _run_semaphore:
        scenario = await _scenario_or_404(session, user, scenario_id)
        _validate_evaluator(scenario.evaluator)
        endpoint = await _endpoint_or_422(
            session, endpoint_override_id or scenario.endpoint_id
        )
        selected_profile_id = metric_profile_id or scenario.metric_profile_id
        metric_profile = None
        metric_profile_items: list[EvaluationMetricProfileItem] = []
        if scenario.evaluator == "deepeval":
            if selected_profile_id is None:
                raise HTTPException(
                    422, "DeepEval multi-turn runs require a metric profile"
                )
            metric_profile, metric_profile_items = await _metric_profile_or_422(
                session, selected_profile_id, expected_mode=EvaluationMode.MULTI_TURN
            )
        _ensure_evaluator_ready(scenario.evaluator)
        turns = list(
            (
                await session.exec(
                    select(EvaluationScenarioTurn)
                    .where(EvaluationScenarioTurn.scenario_id == scenario.id)
                    .order_by(col(EvaluationScenarioTurn.position))
                )
            ).all()
        )
        if not turns:
            raise HTTPException(422, "Add at least one turn before running a scenario")
        for item in metric_profile_items:
            if (
                item.custom_metric_id is not None
                and "expected_outcome" in item.required_keys
                and not any(turn.expected_output.strip() for turn in turns)
            ):
                raise HTTPException(
                    422,
                    "Custom metric requires non-empty execution data: expected_outcome",
                )
        baseline_turns: list[EvaluationScenarioRunTurn] = []
        if baseline_run_id:
            baseline = await session.get(EvaluationScenarioRun, baseline_run_id)
            if not baseline or baseline.scenario_id != scenario.id:
                raise HTTPException(422, "Baseline run must belong to this scenario")
            baseline_turns = list(
                (
                    await session.exec(
                        select(EvaluationScenarioRunTurn).where(
                            EvaluationScenarioRunTurn.run_id == baseline.id
                        )
                    )
                ).all()
            )
        run = EvaluationScenarioRun(
            scenario_id=scenario.id,
            owner_id=user.id,
            baseline_run_id=baseline_run_id,
            evaluator=scenario.evaluator,
            job_id=job_id,
            comparison_group_id=comparison_group_id,
            metric_profile_id=metric_profile.id if metric_profile else None,
            metric_profile_version=metric_profile.version if metric_profile else None,
            metric_profile_snapshot=(
                _metric_profile_snapshot(metric_profile, metric_profile_items)
                if metric_profile
                else None
            ),
        )
        session.add(run)
        await session.flush()
        results: list[EvaluationScenarioRunTurn] = []
        thread_id = str(run.id)
        variables: dict[str, Any] = {
            "previous_output": "",
            "conversation_history": [],
            "thread_id": thread_id,
        }
        conversation: list[tuple[str, str]] = []
        base_headers = decrypt_evaluation_headers(endpoint.encrypted_headers)
        for turn in turns:
            try:
                headers = {
                    **base_headers,
                    **decrypt_evaluation_headers(turn.encrypted_headers),
                }
                status, raw, actual, request_body = await _call_endpoint(
                    _turn_endpoint_url(endpoint, turn.url),
                    headers,
                    turn.body_template,
                    turn.response_path,
                    variables,
                    json_overrides={"thread_id": thread_id},
                )
                user_content = _conversation_user_content(request_body)
                evaluation = (
                    await _evaluate_live_row(
                        user_content,
                        actual,
                        turn.expected_output,
                        turn.position,
                        scenario.threshold,
                        scenario.evaluator,
                    )
                    if comparison_mode != EvaluationComparisonMode.RELATIVE
                    else None
                )
                metric_reason = (
                    next(
                        (
                            metric.reason
                            for metric in evaluation.metrics
                            if metric.reason
                        ),
                        "평가 사유가 제공되지 않았습니다.",
                    )
                    if evaluation
                    else "상대평가 전용 실행으로 절대 품질점수를 계산하지 않았습니다."
                )
                result = EvaluationScenarioRunTurn(
                    run_id=run.id,
                    scenario_turn_id=turn.id,
                    position=turn.position,
                    identifier=turn.identifier,
                    request_body=request_body,
                    actual_output=actual,
                    expected_output=turn.expected_output,
                    response_status=status,
                    response_body=raw,
                    score=evaluation.score if evaluation else 0,
                    passed=evaluation.passed if evaluation else False,
                    reason=metric_reason,
                )
                results.append(result)
                variables["previous_output"] = actual
                variables[turn.identifier] = actual
                conversation.extend([("user", user_content), ("assistant", actual)])
                variables["conversation_history"] = [
                    {"role": role, "content": content} for role, content in conversation
                ]
            except (httpx.HTTPError, ValueError) as exc:
                results.append(
                    EvaluationScenarioRunTurn(
                        run_id=run.id,
                        scenario_turn_id=turn.id,
                        position=turn.position,
                        identifier=turn.identifier,
                        expected_output=turn.expected_output,
                        error=str(exc),
                    )
                )
                run.error = f"Turn '{turn.identifier}' failed; later turns were not called: {exc}"
                break
        session.add_all(results)
        run.total, run.passed = len(results), sum(item.passed for item in results)
        run.failed = run.total - run.passed
        run.turn_average_score = round_score(
            sum(item.score for item in results) / run.total
        )
        if comparison_mode == EvaluationComparisonMode.RELATIVE:
            run.overall_score = 0
            run.overall_passed = False
            run.overall_reason = (
                "상대평가 전용 실행으로 절대 품질점수를 계산하지 않았습니다."
            )
        elif scenario.evaluator == "deepeval" and not run.error:
            try:
                conversation_results = await evaluate_conversation_metrics(
                    [_metric_definition(item) for item in metric_profile_items],
                    turns=conversation,
                    expected_outcome="\n".join(
                        f"{index + 1}. {turn.expected_output}"
                        for index, turn in enumerate(turns)
                        if turn.expected_output.strip()
                    )
                    or None,
                    model_name=settings.DEEPEVAL_MODEL,
                )
                run.metrics = [result.model_dump() for result in conversation_results]
                run.overall_score = aggregate_score(conversation_results)
                run.overall_passed = run.overall_score >= scenario.threshold
                run.overall_reason = (
                    f"선택한 멀티턴 프로필의 가중합은 {run.overall_score:.3f}점이며 "
                    f"임계값 {scenario.threshold:.3f}점에 "
                    f"{'통과했습니다.' if run.overall_passed else '미달했습니다.'}"
                )
            except Exception as exc:
                run.error = f"전체 대화 평가에 실패했습니다: {exc}"[:1_000]
        elif scenario.evaluator == "local":
            run.overall_score = run.turn_average_score
            run.overall_passed = (
                not run.error and run.overall_score >= scenario.threshold
            )
            run.overall_reason = f"로컬 턴 평균은 {run.overall_score:.3f}점입니다."
        if run.error:
            run.overall_passed = False
            run.overall_reason = f"부분 실행: {run.error}"[:4000]
        run.average_score = run.overall_score
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return _scenario_run(run, results, baseline_turns)


async def execute_saved_scenario_job(job: EvaluationJob) -> uuid.UUID:
    if not job.scenario_id:
        raise ValueError("Scenario evaluation job has no scenario target")
    async with AsyncSession(engine, expire_on_commit=False) as session:
        existing_run_id = (
            await session.exec(
                select(EvaluationScenarioRun.id).where(
                    EvaluationScenarioRun.job_id == job.id
                )
            )
        ).first()
        if existing_run_id:
            return existing_run_id
        user = await session.get(User, job.owner_id)
        if not user:
            raise ValueError("Evaluation job owner no longer exists")
        result = await _execute_scenario(
            job.scenario_id,
            session,
            user,
            baseline_run_id=None,
            job_id=job.id,
        )
        return result.id


@router.get(
    "/multi-turn/datasets/{scenario_id}/runs", response_model=ScenarioRunsPublic
)
@router.get(
    "/scenarios/{scenario_id}/runs",
    response_model=ScenarioRunsPublic,
    include_in_schema=False,
)
async def read_scenario_runs(
    scenario_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=MAX_PAGE_SIZE),
) -> ScenarioRunsPublic:
    scenario = await _scenario_or_404(session, user, scenario_id)
    runs = list(
        (
            await session.exec(
                select(EvaluationScenarioRun)
                .where(
                    EvaluationScenarioRun.scenario_id == scenario_id,
                    col(EvaluationScenarioRun.comparison_group_id).is_(None),
                )
                .order_by(col(EvaluationScenarioRun.created_at).desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )
    executors = {
        executor.id: executor
        for executor in (
            await session.exec(
                select(User).where(
                    col(User.id).in_(
                        {run.owner_id for run in runs} or {uuid.UUID(int=0)}
                    )
                )
            )
        ).all()
    }
    return ScenarioRunsPublic(
        data=[
            _scenario_run_summary(run, scenario, executors.get(run.owner_id))
            for run in runs
        ],
        count=await _count(
            session,
            EvaluationScenarioRun,
            EvaluationScenarioRun.scenario_id == scenario_id,
            col(EvaluationScenarioRun.comparison_group_id).is_(None),
        ),
    )


@router.get(
    "/multi-turn/datasets/{scenario_id}/runs/{run_id}",
    response_model=ScenarioRunPublic,
)
@router.get(
    "/scenarios/{scenario_id}/runs/{run_id}",
    response_model=ScenarioRunPublic,
    include_in_schema=False,
)
async def read_scenario_run(
    scenario_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> ScenarioRunPublic:
    scenario = await _scenario_or_404(session, user, scenario_id)
    run = await session.get(EvaluationScenarioRun, run_id)
    if not run or run.scenario_id != scenario_id:
        raise HTTPException(404, "Evaluation scenario run not found")
    turns = list(
        (
            await session.exec(
                select(EvaluationScenarioRunTurn)
                .where(EvaluationScenarioRunTurn.run_id == run.id)
                .order_by(col(EvaluationScenarioRunTurn.position))
            )
        ).all()
    )
    baseline_turns: list[EvaluationScenarioRunTurn] = []
    if run.baseline_run_id:
        baseline_turns = list(
            (
                await session.exec(
                    select(EvaluationScenarioRunTurn).where(
                        EvaluationScenarioRunTurn.run_id == run.baseline_run_id
                    )
                )
            ).all()
        )
    return _scenario_run(
        run,
        turns,
        baseline_turns,
        scenario,
        await session.get(User, run.owner_id),
    )


@router.get("/multi-turn/datasets/{scenario_id}/runs/{run_id}/report.html")
async def download_scenario_run_report(
    scenario_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
) -> HTMLResponse:
    scenario = await _scenario_or_404(session, user, scenario_id)
    run = await session.get(EvaluationScenarioRun, run_id)
    if run is None or run.scenario_id != scenario.id:
        raise HTTPException(404, "Evaluation scenario run not found")
    result = await read_scenario_run(scenario_id, run_id, session, user)

    def escaped(value: object | None) -> str:
        return html.escape("" if value is None else str(value), quote=True)

    def required_keys(item: dict[Any, Any]) -> str:
        value = item.get("required_keys")
        return ", ".join(str(key) for key in value) if isinstance(value, list) else "-"

    metric_rows = "".join(
        "<tr>"
        f"<td>{escaped(metric.display_name or metric.name)}</td>"
        f"<td>{metric.score:.3f}점</td>"
        f"<td>{escaped(metric.weight_percent)}%</td>"
        f"<td>{escaped(metric.weighted_score)}점</td>"
        f"<td>{escaped(metric.reason)}</td>"
        f"<td>{escaped(metric.error)}</td>"
        "</tr>"
        for metric in result.metrics
    )
    turn_rows = "".join(
        "<tr>"
        f"<td>{turn.position + 1} · {escaped(turn.identifier)}</td>"
        f"<td>{escaped(turn.request_body)}</td>"
        f"<td>{escaped(turn.expected_output)}</td>"
        f"<td>{escaped(turn.actual_output)}</td>"
        f"<td>{turn.score:.3f}점</td>"
        f"<td>{escaped(turn.reason or turn.error)}</td>"
        "</tr>"
        for turn in result.turns
    )
    snapshot = run.metric_profile_snapshot or {}
    raw_snapshot_metrics = snapshot.get("metrics") if isinstance(snapshot, dict) else []
    snapshot_metrics = (
        raw_snapshot_metrics if isinstance(raw_snapshot_metrics, list) else []
    )
    custom_rows = "".join(
        "<tr>"
        f"<td>{escaped(item.get('display_name') or item.get('metric_type'))}</td>"
        f"<td>{escaped(item.get('custom_metric_id') or '-')}</td>"
        f"<td>{escaped(item.get('custom_metric_version') or '-')}</td>"
        f"<td>{escaped(required_keys(item))}</td>"
        f"<td>{escaped(item.get('custom_metric_prompt') or '-')}</td>"
        "</tr>"
        for item in snapshot_metrics
        if isinstance(item, dict)
    )
    report = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>멀티턴 평가 리포트</title><style>body{{font-family:system-ui;margin:32px;color:#292524}}table{{width:100%;border-collapse:collapse;margin:16px 0}}th,td{{border:1px solid #ddd;padding:8px;text-align:left;vertical-align:top;white-space:pre-wrap}}.summary{{display:flex;gap:16px;flex-wrap:wrap}}.card{{border:1px solid #ddd;padding:12px;border-radius:8px}}</style></head><body><h1>{escaped(result.scenario_name)} 멀티턴 평가 리포트</h1><div class="summary"><div class="card">종합 {result.overall_score:.3f}점</div><div class="card">임계값 {float(scenario.threshold):.3f}점</div><div class="card">{"통과" if result.overall_passed else "실패"}</div><div class="card">턴 {result.passed}/{result.total} 통과</div></div><p>총점 = Σ(메트릭 0~100 점수 × 가중치 / 100), ROUND_HALF_UP 소수점 셋째 자리. 프로필 범위 {escaped(snapshot.get("evaluation_scope") if isinstance(snapshot, dict) else "-")} · v{escaped(run.metric_profile_version or "-")}.</p><p>{escaped(result.overall_reason)}</p><h2>프로필 스냅샷</h2><table><thead><tr><th>지표</th><th>CustomMetric ID</th><th>버전</th><th>필요 키</th><th>프롬프트</th></tr></thead><tbody>{custom_rows or '<tr><td colspan="5">스냅샷 없음</td></tr>'}</tbody></table><h2>프로필 지표</h2><table><thead><tr><th>지표</th><th>0~100 점수</th><th>가중치</th><th>기여점수</th><th>한국어 사유</th><th>오류</th></tr></thead><tbody>{metric_rows}</tbody></table><h2>턴별 증거</h2><table><thead><tr><th>턴</th><th>요청</th><th>기대 응답</th><th>실제 응답</th><th>점수</th><th>사유</th></tr></thead><tbody>{turn_rows}</tbody></table></body></html>"""
    return HTMLResponse(
        content=report,
        headers={
            "Content-Disposition": f'attachment; filename="multi-turn-report-{run_id}.html"',
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/run", response_model=EvaluationSummary)
async def run_evaluation(
    session: SessionDep,
    _user: CurrentUser,
    file: UploadFile = File(description="UTF-8 CSV or JSON dataset"),
    framework: Framework = Form(default="local"),
    threshold: float = Form(default=70, ge=0, le=100),
    metric_profile_id: uuid.UUID | None = Form(default=None),
) -> EvaluationSummary:
    if framework == "langfuse":
        raise HTTPException(501, "langfuse is scaffolded but not configured.")
    _validate_evaluator(framework)
    content = await file.read(MAX_DATASET_BYTES + 1)
    if len(content) > MAX_DATASET_BYTES:
        raise HTTPException(413, "Dataset cannot exceed 5 MB")
    rows = parse_dataset(file.filename or "dataset", content)
    metric_definitions: list[EvaluationMetricDefinitionCreate] | None = None
    profile: EvaluationMetricProfile | None = None
    if framework == "deepeval":
        if metric_profile_id is None:
            raise HTTPException(422, "DeepEval quick uploads require a metric profile")
        profile, items = await _metric_profile_or_422(
            session,
            metric_profile_id,
            expected_scope=EvaluationScope.QUICK_UPLOAD,
        )
        metric_definitions = [_metric_definition(item) for item in items]
        for definition in metric_definitions:
            if definition.custom_metric_id is None:
                continue
            for row in rows:
                try:
                    ensure_required_values(
                        definition.required_keys,
                        {
                            "input": row.get("input"),
                            "actual_output": row.get("actual_output"),
                            "expected_output": row.get("expected_output"),
                        },
                    )
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
    _ensure_evaluator_ready(framework)
    evaluated: list[EvaluationRow] = []
    for index, row in enumerate(rows):
        if framework == "local":
            evaluated.append(_evaluate_row(row, index, threshold))
        else:
            evaluated.append(
                await _evaluate_live_row(
                    str(row["input"]),
                    str(row["actual_output"]),
                    str(row["expected_output"]),
                    index,
                    threshold,
                    "deepeval",
                    metric_definitions,
                )
            )
    passed = sum(row.passed for row in evaluated)
    return EvaluationSummary(
        framework=framework,
        evaluator=(
            f"DeepEval · {profile.name} v{profile.version}"
            if profile is not None
            else "deterministic-baseline-v1"
        ),
        total=len(evaluated),
        passed=passed,
        failed=len(evaluated) - passed,
        pass_rate=round(passed / len(evaluated), 4),
        average_score=round_score(sum(row.score for row in evaluated) / len(evaluated)),
        rows=evaluated,
    )


@router.get(
    "/multi-turn/datasets/{scenario_id}/turns",
    response_model=EvaluationScenarioTurnsPublic,
)
async def read_scenario_turns(
    scenario_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=200),
) -> EvaluationScenarioTurnsPublic:
    await _scenario_or_404(session, user, scenario_id)
    condition = EvaluationScenarioTurn.scenario_id == scenario_id
    statement = (
        select(EvaluationScenarioTurn)
        .where(condition)
        .order_by(col(EvaluationScenarioTurn.position))
    )
    turns = list((await session.exec(statement.offset(offset).limit(limit))).all())
    return EvaluationScenarioTurnsPublic(
        data=[
            EvaluationScenarioTurnPublic(
                id=turn.id,
                position=turn.position,
                identifier=turn.identifier,
                url=turn.url,
                headers_configured=bool(turn.encrypted_headers),
                body_template=turn.body_template,
                response_path=turn.response_path,
                expected_output=turn.expected_output,
            )
            for turn in turns
        ],
        count=await _count(session, EvaluationScenarioTurn, condition),
    )


@router.post(
    "/multi-turn/datasets/{scenario_id}/turns",
    response_model=EvaluationScenarioTurnPublic,
)
async def create_scenario_turn(
    scenario_id: uuid.UUID,
    turn_in: EvaluationScenarioTurnCreate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationScenarioTurnPublic:
    scenario = await _scenario_or_404(session, user, scenario_id)
    endpoint = await _endpoint_or_422(session, scenario.endpoint_id)
    _reject_sensitive_turn_headers([turn_in], user)
    duplicate = (
        await session.exec(
            select(EvaluationScenarioTurn.id).where(
                EvaluationScenarioTurn.scenario_id == scenario.id,
                EvaluationScenarioTurn.identifier == turn_in.identifier,
            )
        )
    ).first()
    if duplicate:
        raise HTTPException(422, "Each scenario turn identifier must be unique")
    position = await _count(
        session,
        EvaluationScenarioTurn,
        EvaluationScenarioTurn.scenario_id == scenario.id,
    )
    turn = _scenario_turns(scenario.id, [turn_in], endpoint)[0]
    turn.position = position
    session.add(turn)
    await session.commit()
    await session.refresh(turn)
    return EvaluationScenarioTurnPublic(
        id=turn.id,
        position=turn.position,
        identifier=turn.identifier,
        url=turn.url,
        headers_configured=bool(turn.encrypted_headers),
        body_template=turn.body_template,
        response_path=turn.response_path,
        expected_output=turn.expected_output,
    )


@router.put(
    "/multi-turn/datasets/{scenario_id}/turns/{turn_id}",
    response_model=EvaluationScenarioTurnPublic,
)
async def update_scenario_turn(
    scenario_id: uuid.UUID,
    turn_id: uuid.UUID,
    turn_in: EvaluationScenarioTurnCreate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationScenarioTurnPublic:
    scenario = await _scenario_or_404(session, user, scenario_id)
    turn = await session.get(EvaluationScenarioTurn, turn_id)
    if not turn or turn.scenario_id != scenario.id:
        raise HTTPException(404, "Evaluation scenario turn not found")
    duplicate = (
        await session.exec(
            select(EvaluationScenarioTurn.id).where(
                EvaluationScenarioTurn.scenario_id == scenario.id,
                EvaluationScenarioTurn.identifier == turn_in.identifier,
                EvaluationScenarioTurn.id != turn.id,
            )
        )
    ).first()
    if duplicate:
        raise HTTPException(422, "Each scenario turn identifier must be unique")
    endpoint = await _endpoint_or_422(session, scenario.endpoint_id)
    _reject_sensitive_turn_headers([turn_in], user)
    replacement = _scenario_turns(scenario.id, [turn_in], endpoint)[0]
    turn.identifier, turn.url = replacement.identifier, replacement.url
    turn.body_template, turn.response_path = (
        replacement.body_template,
        replacement.response_path,
    )
    turn.expected_output = replacement.expected_output
    if turn_in.headers:
        turn.encrypted_headers = replacement.encrypted_headers
    session.add(turn)
    await session.commit()
    await session.refresh(turn)
    return EvaluationScenarioTurnPublic(
        id=turn.id,
        position=turn.position,
        identifier=turn.identifier,
        url=turn.url,
        headers_configured=bool(turn.encrypted_headers),
        body_template=turn.body_template,
        response_path=turn.response_path,
        expected_output=turn.expected_output,
    )


@router.delete("/multi-turn/datasets/{scenario_id}/turns/{turn_id}")
async def delete_scenario_turn(
    scenario_id: uuid.UUID, turn_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Message:
    scenario = await _scenario_or_404(session, user, scenario_id)
    turn = await session.get(EvaluationScenarioTurn, turn_id)
    if not turn or turn.scenario_id != scenario.id:
        raise HTTPException(404, "Evaluation scenario turn not found")
    await session.delete(turn)
    await session.flush()
    remaining = list(
        (
            await session.exec(
                select(EvaluationScenarioTurn)
                .where(EvaluationScenarioTurn.scenario_id == scenario.id)
                .order_by(col(EvaluationScenarioTurn.position))
            )
        ).all()
    )
    for position, item in enumerate(remaining):
        item.position = position
        session.add(item)
    await session.commit()
    return Message(message="Evaluation scenario turn deleted successfully")


async def _bulk_owned(
    session: SessionDep, user: CurrentUser, model: Any, ids: list[uuid.UUID]
) -> list[Any]:
    statement = select(model).where(col(model.id).in_(ids))
    if not user.is_superuser and hasattr(model, "owner_id"):
        statement = statement.where(model.owner_id == user.id)
    items = list((await session.exec(statement)).all())
    if len(items) != len(ids):
        raise HTTPException(404, "One or more selected resources were not found")
    return items


@router.post("/endpoints/bulk-delete")
async def bulk_disable_endpoints(
    request: BulkDeleteRequest, session: SessionDep, _admin: CurrentSuperuser
) -> Message:
    endpoints = list(
        (
            await session.exec(
                select(EvaluationEndpoint).where(
                    col(EvaluationEndpoint.id).in_(request.ids)
                )
            )
        ).all()
    )
    if len(endpoints) != len(request.ids):
        raise HTTPException(404, "One or more endpoints were not found")
    for endpoint in endpoints:
        endpoint.is_active = False
        endpoint.updated_at = get_datetime_utc()
        session.add(endpoint)
    await session.commit()
    return Message(message=f"Disabled {len(endpoints)} evaluation endpoints")


@router.post("/single-turn/datasets/bulk-delete")
async def bulk_delete_datasets(
    request: BulkDeleteRequest, session: SessionDep, user: CurrentUser
) -> Message:
    items = await _bulk_owned(session, user, EvaluationDataset, request.ids)
    for item in items:
        await session.delete(item)
    await session.commit()
    return Message(message=f"Deleted {len(items)} datasets")


@router.post("/multi-turn/datasets/bulk-delete")
async def bulk_delete_scenarios(
    request: BulkDeleteRequest, session: SessionDep, user: CurrentUser
) -> Message:
    items = await _bulk_owned(session, user, EvaluationScenario, request.ids)
    for item in items:
        await session.delete(item)
    await session.commit()
    return Message(message=f"Deleted {len(items)} scenarios")


@router.post("/comparisons/bulk-delete")
async def bulk_delete_comparisons(
    request: BulkDeleteRequest, session: SessionDep, user: CurrentUser
) -> Message:
    items = await _bulk_owned(session, user, EvaluationComparison, request.ids)
    for item in items:
        await session.delete(item)
    await session.commit()
    return Message(message=f"Deleted {len(items)} comparisons")


@router.post("/schedules/bulk-delete")
async def bulk_delete_schedules(
    request: BulkDeleteRequest, session: SessionDep, user: CurrentUser
) -> Message:
    items = await _bulk_owned(session, user, EvaluationSchedule, request.ids)
    for item in items:
        await session.delete(item)
    await session.commit()
    return Message(message=f"Deleted {len(items)} schedules")


@router.post("/single-turn/datasets/{dataset_id}/rows/bulk-delete")
async def bulk_delete_dataset_rows(
    dataset_id: uuid.UUID,
    request: BulkDeleteRequest,
    session: SessionDep,
    user: CurrentUser,
) -> Message:
    await _dataset_or_404(session, user, dataset_id)
    items = list(
        (
            await session.exec(
                select(EvaluationDatasetRow).where(
                    EvaluationDatasetRow.dataset_id == dataset_id,
                    col(EvaluationDatasetRow.id).in_(request.ids),
                )
            )
        ).all()
    )
    if len(items) != len(request.ids):
        raise HTTPException(404, "One or more dataset rows were not found")
    for item in items:
        await session.delete(item)
    await session.commit()
    return Message(message=f"Deleted {len(items)} dataset rows")


@router.post("/single-turn/datasets/{dataset_id}/runs/bulk-delete")
async def bulk_delete_dataset_runs(
    dataset_id: uuid.UUID,
    request: BulkDeleteRequest,
    session: SessionDep,
    user: CurrentUser,
) -> Message:
    await _dataset_or_404(session, user, dataset_id)
    items = list(
        (
            await session.exec(
                select(EvaluationRun).where(
                    EvaluationRun.dataset_id == dataset_id,
                    col(EvaluationRun.id).in_(request.ids),
                )
            )
        ).all()
    )
    if len(items) != len(request.ids):
        raise HTTPException(404, "One or more evaluation runs were not found")
    for item in items:
        await session.delete(item)
    await session.commit()
    return Message(message=f"Deleted {len(items)} evaluation runs")


@router.post("/multi-turn/datasets/{scenario_id}/turns/bulk-delete")
async def bulk_delete_scenario_turns(
    scenario_id: uuid.UUID,
    request: BulkDeleteRequest,
    session: SessionDep,
    user: CurrentUser,
) -> Message:
    scenario = await _scenario_or_404(session, user, scenario_id)
    items = list(
        (
            await session.exec(
                select(EvaluationScenarioTurn).where(
                    EvaluationScenarioTurn.scenario_id == scenario.id,
                    col(EvaluationScenarioTurn.id).in_(request.ids),
                )
            )
        ).all()
    )
    if len(items) != len(request.ids):
        raise HTTPException(404, "One or more scenario turns were not found")
    for item in items:
        await session.delete(item)
    await session.flush()
    remaining = list(
        (
            await session.exec(
                select(EvaluationScenarioTurn)
                .where(EvaluationScenarioTurn.scenario_id == scenario.id)
                .order_by(col(EvaluationScenarioTurn.position))
            )
        ).all()
    )
    for position, item in enumerate(remaining):
        item.position = position
        session.add(item)
    await session.commit()
    return Message(message=f"Deleted {len(items)} scenario turns")


@router.post("/multi-turn/datasets/{scenario_id}/runs/bulk-delete")
async def bulk_delete_scenario_runs(
    scenario_id: uuid.UUID,
    request: BulkDeleteRequest,
    session: SessionDep,
    user: CurrentUser,
) -> Message:
    await _scenario_or_404(session, user, scenario_id)
    items = list(
        (
            await session.exec(
                select(EvaluationScenarioRun).where(
                    EvaluationScenarioRun.scenario_id == scenario_id,
                    col(EvaluationScenarioRun.id).in_(request.ids),
                )
            )
        ).all()
    )
    if len(items) != len(request.ids):
        raise HTTPException(404, "One or more scenario runs were not found")
    for item in items:
        await session.delete(item)
    await session.commit()
    return Message(message=f"Deleted {len(items)} scenario runs")
