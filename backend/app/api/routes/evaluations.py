import csv
import io
import json
import re
from difflib import SequenceMatcher
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.deps import CurrentUser

router = APIRouter(prefix="/evaluations", tags=["evaluations"])

MAX_DATASET_BYTES = 5 * 1024 * 1024
Framework = Literal["local", "deepeval", "langfuse"]


class MetricScore(BaseModel):
    name: str
    score: float


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
            status_code=422,
            detail=f"Row {index + 1} is missing fields: {', '.join(missing)}",
        )

    input_text = str(row["input"])
    actual = str(row["actual_output"])
    expected = str(row["expected_output"])
    normalized_actual = _normalize(actual)
    normalized_expected = _normalize(expected)
    exact_match = float(normalized_actual == normalized_expected)
    similarity = SequenceMatcher(None, normalized_actual, normalized_expected).ratio()
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


def parse_dataset(filename: str, content: bytes) -> list[dict[str, Any]]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="Dataset must be UTF-8 encoded")

    suffix = filename.lower().rsplit(".", 1)[-1]
    rows: Any
    try:
        if suffix == "csv":
            rows = list(csv.DictReader(io.StringIO(decoded)))
        elif suffix == "json":
            payload = json.loads(decoded)
            rows = payload.get("data") if isinstance(payload, dict) else payload
        else:
            raise HTTPException(
                status_code=415, detail="Only .csv and .json datasets are supported"
            )
    except (csv.Error, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid dataset: {exc}")

    if not isinstance(rows, list) or not rows:
        raise HTTPException(status_code=422, detail="Dataset must contain at least one row")
    if not all(isinstance(row, dict) for row in rows):
        raise HTTPException(status_code=422, detail="Every dataset row must be an object")
    return cast(list[dict[str, Any]], rows)


@router.get("/integrations", response_model=IntegrationsResponse)
async def read_integrations(_current_user: CurrentUser) -> IntegrationsResponse:
    return IntegrationsResponse(
        data=[
            IntegrationStatus(
                id="local",
                label="Local baseline",
                available=True,
                description="Credential-free exact match, similarity, and token recall.",
            ),
            IntegrationStatus(
                id="deepeval",
                label="DeepEval",
                available=False,
                description="Adapter boundary prepared; model and API-key wiring is next.",
            ),
            IntegrationStatus(
                id="langfuse",
                label="Langfuse",
                available=False,
                description="Adapter boundary prepared; project credentials are required.",
            ),
        ]
    )


@router.post("/run", response_model=EvaluationSummary)
async def run_evaluation(
    _current_user: CurrentUser,
    file: Annotated[UploadFile, File(description="UTF-8 CSV or JSON dataset")],
    framework: Annotated[Framework, Form()] = "local",
    threshold: Annotated[float, Form(ge=0, le=1)] = 0.7,
) -> EvaluationSummary:
    if framework != "local":
        raise HTTPException(
            status_code=501,
            detail=f"{framework} is scaffolded but not configured. Use local for now.",
        )

    content = await file.read(MAX_DATASET_BYTES + 1)
    if len(content) > MAX_DATASET_BYTES:
        raise HTTPException(status_code=413, detail="Dataset cannot exceed 5 MB")

    rows = parse_dataset(file.filename or "dataset", content)
    evaluated = [_evaluate_row(row, index, threshold) for index, row in enumerate(rows)]
    passed = sum(row.passed for row in evaluated)
    average = sum(row.score for row in evaluated) / len(evaluated)

    return EvaluationSummary(
        framework=framework,
        evaluator="deterministic-baseline-v1",
        total=len(evaluated),
        passed=passed,
        failed=len(evaluated) - passed,
        pass_rate=round(passed / len(evaluated), 4),
        average_score=round(average, 4),
        rows=evaluated,
    )
