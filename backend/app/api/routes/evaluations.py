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
from urllib.parse import urlsplit

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
from app.evaluation_jobs import enqueue_dataset_job
from app.evaluation_metrics import (
    METRIC_CATALOG,
    catalog_definition,
    ensure_korean_reason,
    evaluate_selected_metrics,
)
from app.models import (
    EvaluationDataset,
    EvaluationDatasetCreate,
    EvaluationDatasetImportResult,
    EvaluationDatasetPublic,
    EvaluationDatasetRow,
    EvaluationDatasetRowCreate,
    EvaluationDatasetRowPublic,
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
    EvaluationScenarioUpdate,
    EvaluationSchedule,
    EvaluationScheduleBase,
    EvaluationScheduleCreate,
    EvaluationSchedulePublic,
    EvaluationSchedulesPublic,
    EvaluationScheduleTargetType,
    EvaluationScheduleType,
    EvaluationScheduleUpdate,
    Message,
    MultiTurnDatasetDocument,
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
TURN_SCORE_WEIGHT = 0.4
CONVERSATION_SCORE_WEIGHT = 0.6


class MetricScore(BaseModel):
    name: str
    score: float
    display_name: str | None = None
    weight_percent: int | None = None
    weighted_score: float | None = None
    raw_score: float | None = None
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
    input: str
    expected_output: str
    actual_output: str
    response_status: int | None
    response_body: str | None
    score: float
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
        return f"정규화된 응답의 문자 단위 유사도는 {score:.2%}입니다."
    if name == "token_recall":
        actual_tokens = set(_normalize(actual).split())
        expected_tokens = set(_normalize(expected).split())
        matched = len(actual_tokens & expected_tokens)
        return (
            f"기대 응답 토큰 {len(expected_tokens)}개 중 {matched}개가 실제 응답에 "
            f"포함되어 있습니다. (포함률 {score:.2%})"
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
    exact_match = float(_normalize(actual) == _normalize(expected))
    similarity = SequenceMatcher(None, _normalize(actual), _normalize(expected)).ratio()
    token_recall = _token_recall(actual, expected)
    score = round((exact_match + similarity + token_recall) / 3, 4)
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
                score=round(similarity, 4),
                reason=_local_metric_reason(
                    "similarity", round(similarity, 4), actual, expected
                ),
            ),
            MetricScore(
                name="token_recall",
                score=round(token_recall, 4),
                reason=_local_metric_reason(
                    "token_recall", round(token_recall, 4), actual, expected
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
        score=round(float(metric.score), 4),
        reason=ensure_korean_reason(
            str(metric.reason or "")[:2_000] or None,
            float(metric.score),
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
                raw_score=result.raw_score,
                score_direction=result.score_direction,
                reason=result.reason,
                error=result.error,
            )
            for result in composite_results
        ]
        final_score = round(sum(metric.weighted_score or 0 for metric in metrics), 4)
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


def _deepeval_conversation(
    turns: list[tuple[str, str]], threshold: float
) -> tuple[float, str | None]:
    """Score the completed conversation, not each request in isolation."""
    _require_deepeval()
    from deepeval.metrics import ConversationalGEval
    from deepeval.test_case import ConversationalTestCase, MultiTurnParams, Turn

    test_case = ConversationalTestCase(
        turns=[Turn(role=role, content=content) for role, content in turns]
    )
    metric = ConversationalGEval(
        name="멀티턴 대화 품질",
        criteria=(
            "어시스턴트 응답이 자연스럽고, 전체 대화에서 문맥을 일관되게 "
            "유지하며, 사용자 요청에 관련되고 유용한지 평가하세요. 이전 턴의 "
            "정보와 제약을 후속 응답이 올바르게 반영했는지 확인하세요. "
            "평가 이유는 반드시 자연스러운 한국어로 작성하세요."
        ),
        evaluation_params=[MultiTurnParams.ROLE, MultiTurnParams.CONTENT],
        threshold=threshold,
        model=settings.DEEPEVAL_MODEL,
    )
    metric.measure(test_case)
    score = round(float(metric.score), 4)
    return score, ensure_korean_reason(
        str(metric.reason or "")[:2_000] or None,
        score,
        settings.DEEPEVAL_MODEL,
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


async def _count(session: SessionDep, model: Any, condition: Any) -> int:
    return int(
        (await session.exec(select(func.count(model.id)).where(condition))).one()
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
        metric_type=item.key,
        weight_percent=item.weight_percent,
    )


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
    session: SessionDep, profile_id: uuid.UUID, *, require_active: bool = True
) -> tuple[EvaluationMetricProfile, list[EvaluationMetricProfileItem]]:
    profile = await session.get(EvaluationMetricProfile, profile_id)
    if not profile:
        raise HTTPException(422, "Selected metric profile does not exist")
    if require_active and not profile.is_active:
        raise HTTPException(422, "Selected metric profile is inactive")
    items = await _metric_profile_items(session, profile.id)
    if not items:
        raise HTTPException(422, "Selected metric profile has no metrics")
    return profile, items


def _metric_profile_public(
    profile: EvaluationMetricProfile, items: list[EvaluationMetricProfileItem]
) -> EvaluationMetricProfilePublic:
    return EvaluationMetricProfilePublic(
        **profile.model_dump(),
        metrics=[
            EvaluationMetricDefinitionPublic(
                id=item.id,
                position=item.position,
                display_name=catalog_definition(
                    _metric_definition(item).metric_type
                ).display_name,
                description=catalog_definition(
                    _metric_definition(item).metric_type
                ).description,
                required_fields=list(
                    catalog_definition(
                        _metric_definition(item).metric_type
                    ).required_fields
                ),
                score_direction=catalog_definition(
                    _metric_definition(item).metric_type
                ).score_direction,
                uses_llm=catalog_definition(
                    _metric_definition(item).metric_type
                ).uses_llm,
                docs_url=catalog_definition(
                    _metric_definition(item).metric_type
                ).docs_url,
                **_metric_definition(item).model_dump(),
            )
            for item in items
        ],
    )


def _metric_profile_snapshot(
    profile: EvaluationMetricProfile, items: list[EvaluationMetricProfileItem]
) -> dict[str, object]:
    return {
        "id": str(profile.id),
        "name": profile.name,
        "version": profile.version,
        "metrics": [
            {
                "metric_type": item.key,
                "display_name": item.display_name,
                "weight_percent": item.weight_percent,
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
        **dataset.model_dump(exclude={"endpoint_url", "headers", "method"}),
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
        metrics = [MetricScore(**metric) for metric in (row.metrics or [])]
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
                score_delta=round(row.score - baseline.score, 4) if baseline else None,
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

    def score(value: float) -> str:
        return f"{value * 100:.2f}점"

    profile_metrics = []
    profile_name = "-"
    if isinstance(metric_profile_snapshot, dict):
        profile_name = str(metric_profile_snapshot.get("name") or "-")
        raw_metrics = metric_profile_snapshot.get("metrics")
        if isinstance(raw_metrics, list):
            profile_metrics = [item for item in raw_metrics if isinstance(item, dict)]
    profile_rows = "".join(
        "<tr>"
        f"<td>{escaped(item.get('display_name') or item.get('metric_type') or item.get('key'))}</td>"
        f"<td>{escaped(item.get('weight_percent'))}%</td>"
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
<div class="summary"><div class="card"><span class="muted">실행자</span><div class="value">{escaped(executor.full_name or executor.email)}</div></div><div class="card"><span class="muted">실행시각</span><div class="value">{escaped(run.created_at)}</div></div><div class="card"><span class="muted">종합 점수</span><div class="value">{score(run.average_score)}</div></div><div class="card"><span class="muted">통과</span><div class="value">{run.passed}/{run.total}</div></div></div>
<h2>평가 프로파일</h2><p class="muted">{escaped(profile_name)} · 실행 스냅샷 v{escaped(run.metric_profile_version or "-")} · 기준 가중치 합계</p><table><thead><tr><th>평가지표</th><th>가중치</th></tr></thead><tbody>{profile_rows or '<tr><td colspan="2">지표 프로파일 스냅샷이 없습니다.</td></tr>'}</tbody></table>
<h2>행별 결과</h2>{"".join(evidence)}
</main></body></html>"""


def _scenario_public(
    scenario: EvaluationScenario,
    turns: list[EvaluationScenarioTurn],
    count: int | None = None,
) -> EvaluationScenarioPublic:
    return EvaluationScenarioPublic(
        **scenario.model_dump(),
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
                score_delta=round(turn.score - baseline.score, 4) if baseline else None,
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
            return payload["message"]
        messages = payload.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                if (
                    isinstance(message, dict)
                    and message.get("role") == "user"
                    and isinstance(message.get("content"), str)
                ):
                    return message["content"]
    return request_body


def _overall_conversation_result(
    *,
    turn_average_score: float,
    conversation_score: float | None,
    conversation_reason: str | None,
    threshold: float,
    passed_turns: int,
    total_turns: int,
    error: str | None,
) -> tuple[float, bool, str]:
    if conversation_score is None:
        overall_score = turn_average_score
        flow_summary = "대화 흐름 점수 없음(로컬 평가 방식)"
        flow_passed = True
    else:
        overall_score = round(
            turn_average_score * TURN_SCORE_WEIGHT
            + conversation_score * CONVERSATION_SCORE_WEIGHT,
            4,
        )
        flow_summary = f"대화 흐름 {conversation_score * 100:.2f}점"
        flow_passed = conversation_score >= threshold
    all_turns_passed = total_turns > 0 and passed_turns == total_turns
    overall_passed = bool(
        not error and all_turns_passed and flow_passed and overall_score >= threshold
    )
    verdict = "통과" if overall_passed else "실패"
    reason = (
        f"종합 {overall_score * 100:.2f}점 ({verdict}) · "
        f"턴별 정확성 {turn_average_score * 100:.2f}점 · {flow_summary}."
    )
    if conversation_reason:
        reason += f" 대화 흐름 판정: {conversation_reason}"
    if error:
        reason += f" 실행 오류: {error}"
    return overall_score, overall_passed, reason[:4_000]


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


@router.get("/metric-profiles", response_model=EvaluationMetricProfilesPublic)
async def read_metric_profiles(
    session: SessionDep, user: CurrentUser
) -> EvaluationMetricProfilesPublic:
    statement = select(EvaluationMetricProfile).order_by(
        col(EvaluationMetricProfile.updated_at).desc()
    )
    if not user.is_superuser:
        statement = statement.where(EvaluationMetricProfile.is_active == True)  # noqa: E712
    profiles = list((await session.exec(statement)).all())
    return EvaluationMetricProfilesPublic(
        data=[
            _metric_profile_public(
                profile, await _metric_profile_items(session, profile.id)
            )
            for profile in profiles
        ],
        count=len(profiles),
    )


@router.get("/metric-catalog", response_model=EvaluationMetricCatalogPublic)
async def read_metric_catalog(_user: CurrentUser) -> EvaluationMetricCatalogPublic:
    data = [
        EvaluationMetricCatalogItem(
            metric_type=metric_type,
            display_name=definition.display_name,
            description=definition.description,
            required_fields=list(definition.required_fields),
            score_direction=definition.score_direction,
            uses_llm=definition.uses_llm,
            docs_url=definition.docs_url,
        )
        for metric_type, definition in METRIC_CATALOG.items()
    ]
    return EvaluationMetricCatalogPublic(data=data, count=len(data))


@router.post("/metric-profiles", response_model=EvaluationMetricProfilePublic)
async def create_metric_profile(
    profile_in: EvaluationMetricProfileCreate,
    session: SessionDep,
    _admin: CurrentSuperuser,
) -> EvaluationMetricProfilePublic:
    profile = EvaluationMetricProfile(**profile_in.model_dump(exclude={"metrics"}))
    session.add(profile)
    await session.flush()
    items = [
        EvaluationMetricProfileItem(
            profile_id=profile.id,
            position=position,
            key=metric.metric_type.value,
            display_name=catalog_definition(metric.metric_type).display_name,
            criteria=catalog_definition(metric.metric_type).description,
            weight_percent=metric.weight_percent,
            evaluation_params=list(
                catalog_definition(metric.metric_type).required_fields
            ),
        )
        for position, metric in enumerate(profile_in.metrics)
    ]
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
    _admin: CurrentSuperuser,
) -> EvaluationMetricProfilePublic:
    profile = await session.get(EvaluationMetricProfile, profile_id)
    if not profile:
        raise HTTPException(404, "Metric profile not found")
    profile.sqlmodel_update(profile_in.model_dump(exclude={"metrics"}))
    profile.version += 1
    profile.updated_at = get_datetime_utc()
    await session.exec(
        delete(EvaluationMetricProfileItem).where(
            col(EvaluationMetricProfileItem.profile_id) == profile.id
        )
    )
    items = [
        EvaluationMetricProfileItem(
            profile_id=profile.id,
            position=position,
            key=metric.metric_type.value,
            display_name=catalog_definition(metric.metric_type).display_name,
            criteria=catalog_definition(metric.metric_type).description,
            weight_percent=metric.weight_percent,
            evaluation_params=list(
                catalog_definition(metric.metric_type).required_fields
            ),
        )
        for position, metric in enumerate(profile_in.metrics)
    ]
    session.add(profile)
    session.add_all(items)
    await session.commit()
    await session.refresh(profile)
    return _metric_profile_public(profile, items)


@router.get("/endpoints", response_model=EvaluationEndpointsPublic)
async def read_endpoints(
    session: SessionDep, _user: CurrentUser
) -> EvaluationEndpointsPublic:
    statement = select(EvaluationEndpoint).order_by(col(EvaluationEndpoint.name))
    if not _user.is_superuser:
        statement = statement.where(EvaluationEndpoint.is_active == True)  # noqa: E712
    endpoints = list((await session.exec(statement)).all())
    return EvaluationEndpointsPublic(
        data=[_endpoint_public(item) for item in endpoints], count=len(endpoints)
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
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
) -> EvaluationDatasetsPublic:
    statement = (
        select(EvaluationDataset)
        .where(EvaluationDataset.evaluation_type == "single_turn")
        .order_by(col(EvaluationDataset.updated_at).desc())
    )
    count_statement = select(func.count(EvaluationDataset.id)).where(
        EvaluationDataset.evaluation_type == "single_turn"
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
                select(
                    EvaluationDatasetRow.dataset_id, func.count(EvaluationDatasetRow.id)
                )
                .where(
                    EvaluationDatasetRow.dataset_id.in_(
                        [item.id for item in datasets] or [uuid.UUID(int=0)]
                    )
                )
                .group_by(EvaluationDatasetRow.dataset_id)
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
        await _metric_profile_or_422(session, dataset_in.metric_profile_id)
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
    limit: int = Query(MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
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
        endpoint_id=dataset.endpoint_id,
        metric_profile_id=dataset.metric_profile_id,
        threshold=dataset.threshold,
        evaluator=cast(Literal["deepeval", "local"], dataset.evaluator),
        cases=[
            {
                "input": row.input,
                "request": EvaluationRequestDocument(
                    headers=row.request_headers or dataset.headers,
                    body=json.loads(row.request_body) if row.request_body else body,
                    actual_output_json_pointer=(
                        row.response_path if row.request_body else dataset.response_path
                    ),
                ),
                "expected_output": row.expected_output,
            }
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
        await _metric_profile_or_422(session, dataset_in.metric_profile_id)
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
) -> None:
    dataset = await _dataset_or_404(session, user, dataset_id)
    _ensure_evaluator_ready(dataset.evaluator)
    if dataset.evaluator == "deepeval":
        if not dataset.metric_profile_id:
            raise HTTPException(422, "DeepEval datasets require a metric profile")
        await _metric_profile_or_422(session, dataset.metric_profile_id)
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
) -> EvaluationJobPublic:
    await _validate_dataset_job_request(dataset_id, session, user, baseline_run_id)
    job = await enqueue_dataset_job(
        session,
        dataset_id=dataset_id,
        owner_id=user.id,
        baseline_run_id=baseline_run_id,
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
) -> SavedRun:
    async with _run_semaphore:
        dataset = await _dataset_or_404(session, user, dataset_id)
        _ensure_evaluator_ready(dataset.evaluator)
        metric_profile: EvaluationMetricProfile | None = None
        metric_profile_items: list[EvaluationMetricProfileItem] = []
        metric_definitions: list[EvaluationMetricDefinitionCreate] | None = None
        if dataset.evaluator == "deepeval" and dataset.metric_profile_id:
            metric_profile, metric_profile_items = await _metric_profile_or_422(
                session, dataset.metric_profile_id
            )
            metric_definitions = [
                _metric_definition(item) for item in metric_profile_items
            ]
        if dataset.evaluator == "deepeval" and not metric_definitions:
            raise HTTPException(422, "DeepEval datasets require a metric profile")
        endpoint = await _endpoint_or_422(session, dataset.endpoint_id)
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
                evaluation = await _evaluate_live_row(
                    row.input,
                    actual,
                    row.expected_output,
                    index,
                    dataset.threshold,
                    dataset.evaluator,
                    metric_definitions,
                )
                saved_row = EvaluationRunRow(
                    run_id=run.id,
                    dataset_row_id=row.id,
                    input=row.input,
                    expected_output=row.expected_output,
                    actual_output=actual,
                    response_status=status,
                    response_body=response_body,
                    score=evaluation.score,
                    passed=evaluation.passed,
                    metrics=[item.model_dump() for item in evaluation.metrics],
                )
                saved.append(saved_row)
                metric_results.extend(
                    EvaluationRunMetricResult(
                        run_row_id=saved_row.id,
                        metric_key=metric.name,
                        display_name=metric.display_name or metric.name,
                        score=metric.score,
                        raw_score=metric.raw_score,
                        score_direction=metric.score_direction or "higher_is_better",
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
                        error=str(exc),
                        metrics=[],
                    )
                )
        await _stage_run_evidence(session, saved, metric_results)
        run.total, run.passed = len(saved), sum(row.passed for row in saved)
        run.failed = run.total - run.passed
        run.pass_rate = round(run.passed / run.total, 4)
        run.average_score = round(sum(row.score for row in saved) / run.total, 4)
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return _saved_run(run, saved, baseline_rows)


async def execute_saved_dataset_job(job: EvaluationJob) -> uuid.UUID:
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
    limit: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
) -> EvaluationSchedulesPublic:
    statement = select(EvaluationSchedule).order_by(
        col(EvaluationSchedule.created_at).desc()
    )
    count_statement = select(func.count(EvaluationSchedule.id))
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
                else scenarios[schedule.scenario_id],
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
    limit: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
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
    limit: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
) -> SavedRunsPublic:
    dataset = await _dataset_or_404(session, user, dataset_id)
    runs = list(
        (
            await session.exec(
                select(EvaluationRun)
                .where(EvaluationRun.dataset_id == dataset_id)
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
            session, EvaluationRun, EvaluationRun.dataset_id == dataset_id
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
    limit: int = Query(MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
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
            url=_assert_url_allowed(endpoint, turn.url),
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
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
) -> EvaluationScenariosPublic:
    statement, count_statement = (
        select(EvaluationScenario).order_by(col(EvaluationScenario.updated_at).desc()),
        select(func.count(EvaluationScenario.id)),
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
                    EvaluationScenarioTurn.scenario_id,
                    func.count(EvaluationScenarioTurn.id),
                )
                .where(
                    EvaluationScenarioTurn.scenario_id.in_(
                        [item.id for item in scenarios] or [uuid.UUID(int=0)]
                    )
                )
                .group_by(EvaluationScenarioTurn.scenario_id)
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
        evaluator=cast(Literal["deepeval", "local"], scenario.evaluator),
        cases=cases,
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
) -> ScenarioRunPublic:
    return await _execute_scenario(
        scenario_id, session, user, baseline_run_id=baseline_run_id
    )


async def _execute_scenario(
    scenario_id: uuid.UUID,
    session: AsyncSession,
    user: User,
    baseline_run_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
) -> ScenarioRunPublic:
    async with _run_semaphore:
        scenario = await _scenario_or_404(session, user, scenario_id)
        _ensure_evaluator_ready(scenario.evaluator)
        endpoint = await _endpoint_or_422(session, scenario.endpoint_id)
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
                    turn.url,
                    headers,
                    turn.body_template,
                    turn.response_path,
                    variables,
                    json_overrides={"thread_id": thread_id},
                )
                user_content = _conversation_user_content(request_body)
                evaluation = await _evaluate_live_row(
                    user_content,
                    actual,
                    turn.expected_output,
                    turn.position,
                    scenario.threshold,
                    scenario.evaluator,
                )
                metric_reason = next(
                    (metric.reason for metric in evaluation.metrics if metric.reason),
                    None,
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
                    score=evaluation.score,
                    passed=evaluation.passed,
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
        run.turn_average_score = round(
            sum(item.score for item in results) / run.total, 4
        )
        if scenario.evaluator == "deepeval" and not run.error:
            try:
                run.geval_score, run.geval_reason = await asyncio.to_thread(
                    _deepeval_conversation, conversation, scenario.threshold
                )
            except Exception as exc:
                run.error = f"전체 대화 평가에 실패했습니다: {exc}"[:1_000]
        run.overall_score, run.overall_passed, run.overall_reason = (
            _overall_conversation_result(
                turn_average_score=run.turn_average_score,
                conversation_score=run.geval_score,
                conversation_reason=run.geval_reason,
                threshold=scenario.threshold,
                passed_turns=run.passed,
                total_turns=run.total,
                error=run.error,
            )
        )
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
    limit: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
) -> ScenarioRunsPublic:
    scenario = await _scenario_or_404(session, user, scenario_id)
    runs = list(
        (
            await session.exec(
                select(EvaluationScenarioRun)
                .where(EvaluationScenarioRun.scenario_id == scenario_id)
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


@router.post("/run", response_model=EvaluationSummary)
async def run_evaluation(
    _user: CurrentUser,
    file: UploadFile = File(description="UTF-8 CSV or JSON dataset"),
    framework: Framework = Form(default="local"),
    threshold: float = Form(default=0.7, ge=0, le=1),
) -> EvaluationSummary:
    if framework != "local":
        raise HTTPException(
            501, f"{framework} is scaffolded but not configured. Use local for now."
        )
    content = await file.read(MAX_DATASET_BYTES + 1)
    if len(content) > MAX_DATASET_BYTES:
        raise HTTPException(413, "Dataset cannot exceed 5 MB")
    evaluated = [
        _evaluate_row(row, index, threshold)
        for index, row in enumerate(parse_dataset(file.filename or "dataset", content))
    ]
    passed = sum(row.passed for row in evaluated)
    return EvaluationSummary(
        framework=framework,
        evaluator="deterministic-baseline-v1",
        total=len(evaluated),
        passed=passed,
        failed=len(evaluated) - passed,
        pass_rate=round(passed / len(evaluated), 4),
        average_score=round(sum(row.score for row in evaluated) / len(evaluated), 4),
        rows=evaluated,
    )
