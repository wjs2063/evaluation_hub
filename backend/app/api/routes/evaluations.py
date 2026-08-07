import asyncio
import csv
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
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import CurrentSuperuser, CurrentUser, SessionDep
from app.core.config import settings
from app.core.security import decrypt_evaluation_headers, encrypt_evaluation_headers
from app.models import (
    EvaluationDataset,
    EvaluationDatasetCreate,
    EvaluationDatasetImportResult,
    EvaluationDatasetPublic,
    EvaluationDatasetRow,
    EvaluationDatasetRowCreate,
    EvaluationDatasetRowPublic,
    EvaluationDatasetRowUpdate,
    EvaluationDatasetsPublic,
    EvaluationDatasetUpdate,
    EvaluationEndpoint,
    EvaluationEndpointCreate,
    EvaluationEndpointPublic,
    EvaluationEndpointsPublic,
    EvaluationEndpointUpdate,
    EvaluationRun,
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
    Message,
    get_datetime_utc,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
MAX_DATASET_BYTES = 5 * 1024 * 1024
MAX_SAVED_DATASET_BYTES = 100 * 1024 * 1024
MAX_PAGE_SIZE = 200
MAX_EXECUTION_ROWS = 1_000
MAX_RESPONSE_BYTES = 1_000_000
Framework = Literal["local", "deepeval", "langfuse"]
_run_semaphore = asyncio.Semaphore(settings.EVALUATION_MAX_CONCURRENT_RUNS)
TURN_SCORE_WEIGHT = 0.4
CONVERSATION_SCORE_WEIGHT = 0.6


class MetricScore(BaseModel):
    name: str
    score: float
    reason: str | None = None


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


class ScenarioRunPublic(BaseModel):
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
    turns: list[ScenarioRunTurnPublic]


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _token_recall(actual: str, expected: str) -> float:
    actual_tokens = set(_normalize(actual).split())
    expected_tokens = set(_normalize(expected).split())
    if not expected_tokens:
        return 1.0 if not actual_tokens else 0.0
    return len(actual_tokens & expected_tokens) / len(expected_tokens)


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
            MetricScore(name="exact_match", score=exact_match),
            MetricScore(name="similarity", score=round(similarity, 4)),
            MetricScore(name="token_recall", score=round(token_recall, 4)),
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
        reason=str(metric.reason or "")[:2_000] or None,
    )


async def _evaluate_live_row(
    input_text: str,
    actual: str,
    expected: str,
    index: int,
    threshold: float,
    evaluator: str,
) -> EvaluationRow:
    if evaluator == "local":
        return _evaluate_row(
            {"input": input_text, "actual_output": actual, "expected_output": expected},
            index,
            threshold,
        )
    if evaluator != "deepeval":
        raise ValueError("Evaluator must be 'deepeval' or 'local'")
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
    return round(float(metric.score), 4), str(metric.reason or "")[:2_000] or None


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
    if not dataset:
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


def _dataset_public(
    dataset: EvaluationDataset,
    rows: list[EvaluationDatasetRow],
    row_count: int | None = None,
) -> EvaluationDatasetPublic:
    return EvaluationDatasetPublic(
        **dataset.model_dump(exclude={"endpoint_url", "headers", "method"}),
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
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif (
            isinstance(current, list)
            and segment.isdigit()
            and int(segment) < len(current)
        ):
            current = current[int(segment)]
        else:
            raise ValueError(f"Response path '{path}' was not found")
    return current


async def _call_endpoint(
    url: str,
    headers: dict[str, str],
    template: str,
    response_path: str | None,
    variables: dict[str, Any],
) -> tuple[int, str, str, str]:
    body, is_json = _request_body(template, variables)
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


def _run_summary(run: EvaluationRun) -> SavedRunSummary:
    return SavedRunSummary(
        **run.model_dump(exclude={"created_at"}), created_at=run.created_at.isoformat()
    )


def _saved_run(
    run: EvaluationRun,
    rows: list[EvaluationRunRow],
    baseline_rows: list[EvaluationRunRow] | None = None,
) -> SavedRun:
    baseline_by_dataset = {row.dataset_row_id: row for row in baseline_rows or []}
    serialized: list[SavedRunRow] = []
    for row in rows:
        baseline = baseline_by_dataset.get(row.dataset_row_id)
        serialized.append(
            SavedRunRow(
                **row.model_dump(exclude={"metrics"}),
                metrics=[MetricScore(**metric) for metric in (row.metrics or [])],
                baseline_actual_output=baseline.actual_output if baseline else None,
                output_changed=(row.actual_output != baseline.actual_output)
                if baseline
                else None,
                score_delta=round(row.score - baseline.score, 4) if baseline else None,
            )
        )
    return SavedRun(
        **_run_summary(run).model_dump(), rows=serialized, row_count=len(serialized)
    )


def _scenario_public(
    scenario: EvaluationScenario,
    turns: list[EvaluationScenarioTurn],
    count: int | None = None,
) -> EvaluationScenarioPublic:
    return EvaluationScenarioPublic(
        **scenario.model_dump(),
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
) -> ScenarioRunPublic:
    baseline_by_identifier = {turn.identifier: turn for turn in baseline_turns or []}
    return ScenarioRunPublic(
        **run.model_dump(exclude={"created_at"}),
        conversation_score=run.geval_score,
        conversation_reason=run.geval_reason,
        created_at=run.created_at.isoformat(),
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
        flow_summary = f"대화 흐름 {conversation_score:.0%}"
        flow_passed = conversation_score >= threshold
    all_turns_passed = total_turns > 0 and passed_turns == total_turns
    overall_passed = bool(
        not error and all_turns_passed and flow_passed and overall_score >= threshold
    )
    verdict = "통과" if overall_passed else "실패"
    reason = (
        f"종합 {overall_score:.0%} ({verdict}) · "
        f"턴별 정확성 {turn_average_score:.0%} · {flow_summary}."
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


@router.get("/datasets", response_model=EvaluationDatasetsPublic)
async def read_datasets(
    session: SessionDep,
    user: CurrentUser,
    evaluation_type: str | None = Query(default=None, max_length=32),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
) -> EvaluationDatasetsPublic:
    statement = select(EvaluationDataset).order_by(
        col(EvaluationDataset.updated_at).desc()
    )
    count_statement = select(func.count(EvaluationDataset.id))
    if not user.is_superuser:
        statement, count_statement = (
            statement.where(EvaluationDataset.owner_id == user.id),
            count_statement.where(EvaluationDataset.owner_id == user.id),
        )
    if evaluation_type:
        statement, count_statement = (
            statement.where(EvaluationDataset.evaluation_type == evaluation_type),
            count_statement.where(EvaluationDataset.evaluation_type == evaluation_type),
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


@router.post("/datasets", response_model=EvaluationDatasetPublic)
async def create_dataset(
    dataset_in: EvaluationDatasetCreate, session: SessionDep, user: CurrentUser
) -> EvaluationDatasetPublic:
    if dataset_in.endpoint_id:
        await _endpoint_or_422(session, dataset_in.endpoint_id)
    if dataset_in.headers:
        raise HTTPException(
            422, "Request headers must be configured on the managed A server"
        )
    _validate_evaluator(dataset_in.evaluator)
    dataset = EvaluationDataset(
        **dataset_in.model_dump(exclude={"rows", "headers"}),
        method="POST",
        headers={},
        owner_id=user.id,
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


@router.post(
    "/datasets/{dataset_id}/import", response_model=EvaluationDatasetImportResult
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
    session.add(dataset)
    await session.commit()
    return EvaluationDatasetImportResult(
        imported=len(rows),
        row_count=await _count(
            session, EvaluationDatasetRow, EvaluationDatasetRow.dataset_id == dataset.id
        ),
    )


@router.get("/datasets/{dataset_id}", response_model=EvaluationDatasetPublic)
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


@router.put("/datasets/{dataset_id}", response_model=EvaluationDatasetPublic)
async def update_dataset(
    dataset_id: uuid.UUID,
    dataset_in: EvaluationDatasetUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationDatasetPublic:
    dataset = await _dataset_or_404(session, user, dataset_id)
    if dataset_in.endpoint_id:
        await _endpoint_or_422(session, dataset_in.endpoint_id)
    if dataset_in.headers:
        raise HTTPException(
            422, "Request headers must be configured on the managed A server"
        )
    if dataset_in.evaluator is not None:
        _validate_evaluator(dataset_in.evaluator)
    dataset.sqlmodel_update(
        dataset_in.model_dump(exclude_unset=True, exclude={"headers"})
    )
    dataset.updated_at = get_datetime_utc()
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


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(
    dataset_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Message:
    dataset = await _dataset_or_404(session, user, dataset_id)
    await session.delete(dataset)
    await session.commit()
    return Message(message="Evaluation dataset deleted successfully")


@router.post("/datasets/{dataset_id}/rows", response_model=EvaluationDatasetRowPublic)
async def create_dataset_row(
    dataset_id: uuid.UUID,
    row_in: EvaluationDatasetRowCreate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationDatasetRow:
    await _dataset_or_404(session, user, dataset_id)
    row = EvaluationDatasetRow(**row_in.model_dump(), dataset_id=dataset_id)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.put(
    "/datasets/{dataset_id}/rows/{row_id}", response_model=EvaluationDatasetRowPublic
)
async def update_dataset_row(
    dataset_id: uuid.UUID,
    row_id: uuid.UUID,
    row_in: EvaluationDatasetRowUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> EvaluationDatasetRow:
    await _dataset_or_404(session, user, dataset_id)
    row = await session.get(EvaluationDatasetRow, row_id)
    if not row or row.dataset_id != dataset_id:
        raise HTTPException(404, "Evaluation dataset row not found")
    row.sqlmodel_update(row_in.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/datasets/{dataset_id}/rows/{row_id}")
async def delete_dataset_row(
    dataset_id: uuid.UUID, row_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Message:
    await _dataset_or_404(session, user, dataset_id)
    row = await session.get(EvaluationDatasetRow, row_id)
    if not row or row.dataset_id != dataset_id:
        raise HTTPException(404, "Evaluation dataset row not found")
    await session.delete(row)
    await session.commit()
    return Message(message="Evaluation dataset row deleted successfully")


@router.post("/datasets/{dataset_id}/run", response_model=SavedRun)
async def run_saved_dataset(
    dataset_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    baseline_run_id: uuid.UUID | None = Query(default=None),
) -> SavedRun:
    async with _run_semaphore:
        dataset = await _dataset_or_404(session, user, dataset_id)
        _ensure_evaluator_ready(dataset.evaluator)
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
        )
        session.add(run)
        await session.flush()
        saved: list[EvaluationRunRow] = []
        try:
            # Dataset headers were a legacy plaintext field. Credentials now
            # live exclusively on the administrator-managed endpoint.
            headers = decrypt_evaluation_headers(endpoint.encrypted_headers)
        except Exception as exc:
            raise HTTPException(500, "Unable to read the endpoint credentials") from exc
        for index, row in enumerate(rows):
            try:
                status, response_body, actual, _ = await _call_endpoint(
                    endpoint.base_url,
                    headers,
                    dataset.body_template,
                    dataset.response_path,
                    {"input": row.input},
                )
                evaluation = await _evaluate_live_row(
                    row.input,
                    actual,
                    row.expected_output,
                    index,
                    dataset.threshold,
                    dataset.evaluator,
                )
                saved.append(
                    EvaluationRunRow(
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
        session.add_all(saved)
        run.total, run.passed = len(saved), sum(row.passed for row in saved)
        run.failed = run.total - run.passed
        run.pass_rate = round(run.passed / run.total, 4)
        run.average_score = round(sum(row.score for row in saved) / run.total, 4)
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return _saved_run(run, saved, baseline_rows)


@router.get("/datasets/{dataset_id}/runs", response_model=SavedRunsPublic)
async def read_saved_runs(
    dataset_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
) -> SavedRunsPublic:
    await _dataset_or_404(session, user, dataset_id)
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
    return SavedRunsPublic(
        data=[_run_summary(run) for run in runs],
        count=await _count(
            session, EvaluationRun, EvaluationRun.dataset_id == dataset_id
        ),
    )


@router.get("/datasets/{dataset_id}/runs/{run_id}", response_model=SavedRun)
async def read_saved_run(
    dataset_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> SavedRun:
    await _dataset_or_404(session, user, dataset_id)
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
    result = _saved_run(run, rows, baseline_rows)
    result.row_count = await _count(
        session, EvaluationRunRow, EvaluationRunRow.run_id == run.id
    )
    return result


def _scenario_turns(
    scenario_id: uuid.UUID,
    turns: list[EvaluationScenarioTurnCreate],
    endpoint: EvaluationEndpoint,
) -> list[EvaluationScenarioTurn]:
    identifiers = [turn.identifier for turn in turns]
    if len(set(identifiers)) != len(identifiers):
        raise HTTPException(422, "Each scenario turn identifier must be unique")
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


@router.get("/scenarios", response_model=EvaluationScenariosPublic)
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


@router.post("/scenarios", response_model=EvaluationScenarioPublic)
async def create_scenario(
    scenario_in: EvaluationScenarioCreate, session: SessionDep, user: CurrentUser
) -> EvaluationScenarioPublic:
    endpoint = await _endpoint_or_422(session, scenario_in.endpoint_id)
    _validate_evaluator(scenario_in.evaluator)
    _reject_sensitive_turn_headers(scenario_in.turns, user)
    scenario = EvaluationScenario(
        **scenario_in.model_dump(exclude={"turns", "endpoint_id"}),
        endpoint_id=endpoint.id,
        owner_id=user.id,
    )
    session.add(scenario)
    await session.flush()
    turns = _scenario_turns(scenario.id, scenario_in.turns, endpoint)
    session.add_all(turns)
    await session.commit()
    await session.refresh(scenario)
    return _scenario_public(scenario, turns)


@router.post("/scenarios/import", response_model=EvaluationScenarioPublic)
async def import_scenario(
    file: UploadFile, session: SessionDep, user: CurrentUser
) -> EvaluationScenarioPublic:
    content = await file.read(MAX_DATASET_BYTES + 1)
    if len(content) > MAX_DATASET_BYTES:
        raise HTTPException(413, "Scenario cannot exceed 5 MB")
    try:
        scenario_in = EvaluationScenarioCreate.model_validate_json(content)
    except ValueError as exc:
        raise HTTPException(422, f"Invalid scenario JSON: {exc}")
    return await create_scenario(scenario_in, session, user)


@router.get("/scenarios/{scenario_id}", response_model=EvaluationScenarioPublic)
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


@router.put("/scenarios/{scenario_id}", response_model=EvaluationScenarioPublic)
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


@router.delete("/scenarios/{scenario_id}")
async def delete_scenario(
    scenario_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Message:
    scenario = await _scenario_or_404(session, user, scenario_id)
    await session.delete(scenario)
    await session.commit()
    return Message(message="Evaluation scenario deleted successfully")


@router.post("/scenarios/{scenario_id}/run", response_model=ScenarioRunPublic)
async def run_scenario(
    scenario_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    baseline_run_id: uuid.UUID | None = Query(default=None),
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
        )
        session.add(run)
        await session.flush()
        results: list[EvaluationScenarioRunTurn] = []
        variables: dict[str, Any] = {
            "previous_output": "",
            "conversation_history": [],
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
                    turn.url, headers, turn.body_template, turn.response_path, variables
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


@router.get("/scenarios/{scenario_id}/runs", response_model=list[ScenarioRunPublic])
async def read_scenario_runs(
    scenario_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
) -> list[ScenarioRunPublic]:
    await _scenario_or_404(session, user, scenario_id)
    runs = list(
        (
            await session.exec(
                select(EvaluationScenarioRun)
                .where(EvaluationScenarioRun.scenario_id == scenario_id)
                .order_by(col(EvaluationScenarioRun.created_at).desc())
                .limit(limit)
            )
        ).all()
    )
    output: list[ScenarioRunPublic] = []
    for run in runs:
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
        output.append(_scenario_run(run, turns, baseline_turns))
    return output


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
