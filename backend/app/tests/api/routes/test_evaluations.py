import asyncio
import importlib.util
import json
import os
import socket
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from app.api.routes import evaluations
from app.api.routes.evaluations import (
    _assert_url_allowed,
    _call_endpoint,
    _conversation_user_content,
    _evaluate_live_row,
    _evaluate_row,
    _extract_response,
    _html_report,
    _import_rows,
    _openai_api_key,
    _replace_variables,
    _request_body,
    _require_deepeval,
    _saved_run,
    _scenario_run,
    _stage_run_evidence,
    _validate_external_url,
    create_endpoint,
    create_scenario,
    parse_dataset,
)
from app.core.config import settings
from app.core.security import decrypt_evaluation_headers, encrypt_evaluation_headers
from app.cron_schedule import CronExpressionError, next_cron_run
from app.evaluation_metrics import METRIC_CATALOG, evaluate_selected_metrics
from app.models import (
    EvaluationDataset,
    EvaluationDatasetCreate,
    EvaluationEndpoint,
    EvaluationEndpointCreate,
    EvaluationMetricDefinitionCreate,
    EvaluationMetricProfileCreate,
    EvaluationMetricType,
    EvaluationRun,
    EvaluationRunMetricResult,
    EvaluationRunRow,
    EvaluationScenarioCreate,
    EvaluationScenarioRun,
    EvaluationScenarioRunTurn,
    EvaluationScheduleCreate,
    EvaluationScheduleTargetType,
    EvaluationScheduleType,
    MultiTurnDatasetDocument,
    SingleTurnDatasetDocument,
    User,
)


def test_single_and_multi_turn_dataset_contracts_are_independent() -> None:
    single = EvaluationDatasetCreate(
        name="싱글턴 데이터셋",
        evaluator="local",
        evaluation_type="single_turn",
    )
    assert single.evaluation_type == "single_turn"

    with pytest.raises(ValueError, match="single_turn"):
        EvaluationDatasetCreate.model_validate(
            {
                "name": "잘못된 멀티턴 데이터셋",
                "evaluator": "local",
                "evaluation_type": "multi_turn",
            }
        )

    paths = {
        path
        for route in evaluations.router.routes
        if (path := getattr(route, "path", None)) is not None
    }
    assert "/evaluations/single-turn/datasets" in paths
    assert "/evaluations/single-turn/datasets/{dataset_id}/run" in paths
    assert "/evaluations/single-turn/datasets/{dataset_id}/export" in paths
    assert "/evaluations/multi-turn/datasets" in paths
    assert "/evaluations/multi-turn/datasets/{scenario_id}/run" in paths
    assert "/evaluations/multi-turn/datasets/{scenario_id}/export" in paths


def test_dataset_documents_require_matching_types_and_request_shapes() -> None:
    endpoint_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    single = SingleTurnDatasetDocument.model_validate(
        {
            "name": "싱글턴",
            "test_type": "single_turn",
            "endpoint_id": str(endpoint_id),
            "metric_profile_id": str(profile_id),
            "cases": [
                {
                    "input": "질문",
                    "request": {
                        "headers": {"Content-Type": "application/json"},
                        "body": {"message": "질문"},
                        "actual_output_json_pointer": "/data/answer",
                    },
                    "expected_output": "기대 답변",
                }
            ],
        }
    )
    assert single.cases[0].request.body == {"message": "질문"}

    with pytest.raises(ValueError, match="single_turn"):
        SingleTurnDatasetDocument.model_validate(
            {
                **single.model_dump(mode="json"),
                "test_type": "multi_turn",
            }
        )

    multi = MultiTurnDatasetDocument.model_validate(
        {
            "name": "멀티턴",
            "test_type": "multi_turn",
            "endpoint_id": str(endpoint_id),
            "evaluator": "local",
            "cases": [
                {
                    "identifier": "turn_1",
                    "request": {
                        "url": "https://example.com/chat",
                        "headers": {},
                        "body": {"message": "첫 질문"},
                        "actual_output_json_pointer": None,
                    },
                    "expected_output": "첫 답변",
                }
            ],
        }
    )
    assert multi.test_type == "multi_turn"


def test_actual_output_extraction_supports_json_pointer_and_full_payload() -> None:
    payload = {"data": {"answers": [{"text/value": "동적 응답"}]}}

    assert _extract_response(payload, "/data/answers/0/text~1value") == "동적 응답"
    assert _extract_response(payload, None) == payload
    assert _extract_response(payload, "data.answers.0.text/value") == "동적 응답"

    with pytest.raises(ValueError, match="was not found"):
        _extract_response(payload, "/data/missing")


def test_schedule_configuration_supports_only_interval_or_cron() -> None:
    target_id = uuid.uuid4()
    interval = EvaluationScheduleCreate(
        name="매시간",
        target_type=EvaluationScheduleTargetType.SINGLE_TURN,
        target_id=target_id,
        schedule_type=EvaluationScheduleType.INTERVAL,
        interval_seconds=3600,
    )
    cron = EvaluationScheduleCreate(
        name="평일 오전",
        target_type=EvaluationScheduleTargetType.MULTI_TURN,
        target_id=target_id,
        schedule_type=EvaluationScheduleType.CRON,
        cron_expression="0 9 * * 1-5",
        timezone="Asia/Seoul",
    )

    assert interval.cron_expression is None
    assert cron.interval_seconds is None
    assert next_cron_run(
        cron.cron_expression or "",
        datetime(2026, 8, 9, tzinfo=UTC),
        cron.timezone,
    ) == datetime(2026, 8, 10, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="require cron_expression"):
        EvaluationScheduleCreate(
            name="잘못된 Cron",
            target_type=EvaluationScheduleTargetType.SINGLE_TURN,
            target_id=target_id,
            schedule_type=EvaluationScheduleType.CRON,
        )
    with pytest.raises(CronExpressionError, match="five years"):
        next_cron_run("0 0 31 2 *", datetime(2026, 1, 1, tzinfo=UTC), "UTC")


def _dynamic_metrics() -> list[EvaluationMetricDefinitionCreate]:
    return [
        EvaluationMetricDefinitionCreate(
            metric_type=EvaluationMetricType.GEVAL_CORRECTNESS,
            weight_percent=60,
        ),
        EvaluationMetricDefinitionCreate(
            metric_type=EvaluationMetricType.GEVAL_PROFESSIONALISM,
            weight_percent=40,
        ),
    ]


def test_html_report_uses_saved_metric_snapshot_and_escapes_evidence() -> None:
    owner_id = uuid.uuid4()
    dataset = EvaluationDataset(
        id=uuid.uuid4(),
        owner_id=owner_id,
        name="품질 <script>alert(1)</script>",
        description="관리자가 선택한 평가지표 결과",
        body_template="{}",
    )
    executor = User(
        id=owner_id,
        email="operator@example.com",
        full_name="실행자",
        hashed_password="unused",
    )
    run = EvaluationRun(
        dataset_id=dataset.id,
        owner_id=owner_id,
        evaluator="deepeval",
        total=1,
        passed=1,
        failed=0,
        pass_rate=1,
        average_score=82,
        metric_profile_version=3,
    )
    row = EvaluationRunRow(
        run_id=run.id,
        input="<img src=x onerror=alert(1)>",
        expected_output="기대 응답",
        actual_output="실제 응답",
        score=82,
        passed=True,
        metrics=[
            {
                "name": "geval_correctness",
                "display_name": "정확성",
                "score": 82,
                "weight_percent": 100,
                "weighted_score": 82,
                "reason": "필수 조건을 충족했습니다.",
            }
        ],
    )

    report = _html_report(
        _saved_run(run, [row], dataset=dataset, executor=executor),
        dataset,
        executor,
        {
            "name": "가중 프로필",
            "evaluation_scope": "single_turn",
            "metrics": [
                {
                    "metric_type": "geval_correctness",
                    "custom_metric_id": "custom-id",
                    "custom_metric_version": 4,
                    "required_keys": ["input", "actual_output"],
                    "custom_metric_prompt": "<script>alert(2)</script>{{input}}",
                    "weight_percent": 100,
                }
            ],
        },
    )

    assert "geval_correctness" in report
    assert "100%" in report
    assert "82.00점" in report
    assert "필수 조건을 충족했습니다." in report
    assert "총점 = Σ" in report
    assert "범위 single_turn" in report
    assert "custom-id" in report
    assert "&lt;script&gt;alert(2)&lt;/script&gt;{{input}}" in report
    assert "<script>alert(2)</script>" not in report
    assert "<script>alert(1)</script>" not in report
    assert "<img src=x onerror=alert(1)>" not in report
    assert "&lt;img src=x onerror=alert(1)&gt;" in report


def test_metric_profile_requires_catalog_types_and_exact_weights() -> None:
    profile = EvaluationMetricProfileCreate(
        name="상담 품질", metrics=_dynamic_metrics()
    )

    assert sum(metric.weight_percent for metric in profile.metrics) == 100

    with pytest.raises(ValueError, match="100 percent"):
        EvaluationMetricProfileCreate(
            name="잘못된 가중치",
            metrics=[_dynamic_metrics()[0]],
        )
    with pytest.raises(ValueError, match="100 percent"):
        EvaluationMetricProfileCreate(
            name="초과된 가중치",
            metrics=[
                EvaluationMetricDefinitionCreate(
                    metric_type=EvaluationMetricType.GEVAL_CORRECTNESS,
                    weight_percent=70,
                ),
                EvaluationMetricDefinitionCreate(
                    metric_type=EvaluationMetricType.ANSWER_RELEVANCY,
                    weight_percent=40,
                ),
            ],
        )
    with pytest.raises(ValueError, match="Input should be"):
        EvaluationMetricDefinitionCreate.model_validate(
            {"metric_type": "administrator_typo", "weight_percent": 100}
        )
    assert set(METRIC_CATALOG) == set(EvaluationMetricType)


def test_selected_metrics_use_deepeval_and_server_weights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[EvaluationMetricType] = []
    active_metrics = 0
    max_active_metrics = 0

    async def translate_reasons(reasons: list[str], model_name: str) -> list[str]:
        assert reasons == ["Official metric judgment", "Official metric judgment"]
        assert model_name == "judge-model"
        return ["공식 지표 판정입니다.", "공식 지표 판정입니다."]

    class Metric:
        def __init__(self, metric_type: EvaluationMetricType) -> None:
            self.metric_type = metric_type
            self.score = 0.9 if metric_type == "geval_correctness" else 0.5
            self.reason = "Official metric judgment"

        async def a_measure(self, _test_case: object) -> float:
            nonlocal active_metrics, max_active_metrics
            active_metrics += 1
            max_active_metrics = max(max_active_metrics, active_metrics)
            calls.append(self.metric_type)
            await asyncio.sleep(0)
            active_metrics -= 1
            return self.score

    monkeypatch.setattr(
        "app.evaluation_metrics._build_metric",
        lambda metric_type, *_args: Metric(metric_type),
    )
    monkeypatch.setattr(
        "app.evaluation_metrics._generate_korean_reasons",
        translate_reasons,
    )
    results = asyncio.run(
        evaluate_selected_metrics(
            _dynamic_metrics(),
            input_text="환불 기간은?",
            actual_output="30일입니다.",
            expected_output="30일",
            model_name="judge-model",
        )
    )

    assert calls == [
        EvaluationMetricType.GEVAL_CORRECTNESS,
        EvaluationMetricType.GEVAL_PROFESSIONALISM,
    ]
    assert max_active_metrics == 1
    assert [result.name for result in results] == [
        "geval_correctness",
        "geval_professionalism",
    ]
    assert [result.weighted_score for result in results] == [54, 20]
    assert [result.reason for result in results] == [
        "공식 지표 판정입니다.",
        "공식 지표 판정입니다.",
    ]


def test_lower_is_better_metric_preserves_raw_score_and_inverts_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Toxicity:
        score = 0.2
        reason = "유해 표현 비율이 낮습니다."

        async def a_measure(self, _test_case: object) -> float:
            return self.score

    monkeypatch.setattr(
        "app.evaluation_metrics._build_metric",
        lambda *_args: Toxicity(),
    )
    result = asyncio.run(
        evaluate_selected_metrics(
            [
                EvaluationMetricDefinitionCreate(
                    metric_type=EvaluationMetricType.TOXICITY, weight_percent=100
                )
            ],
            input_text="질문",
            actual_output="응답",
            expected_output="기대 응답",
            model_name="judge-model",
        )
    )[0]

    assert result.raw_score_ratio == 0.2
    assert result.score == 80
    assert result.weighted_score == 80
    assert result.score_direction == "lower_is_better"


def test_live_row_uses_weighted_composite_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def evaluate_once(*_args: object, **_kwargs: object) -> list[object]:
        return [
            type(
                "Result",
                (),
                {
                    "name": "geval_correctness",
                    "display_name": "정확성 (G-Eval)",
                    "score": 90,
                    "raw_score_ratio": 0.9,
                    "score_direction": "higher_is_better",
                    "weight_percent": 60,
                    "weighted_score": 54,
                    "reason": "정확합니다.",
                    "error": None,
                },
            )(),
            type(
                "Result",
                (),
                {
                    "name": "geval_professionalism",
                    "display_name": "전문성 (G-Eval)",
                    "score": 50,
                    "raw_score_ratio": 0.5,
                    "score_direction": "higher_is_better",
                    "weight_percent": 40,
                    "weighted_score": 20,
                    "reason": "보통입니다.",
                    "error": None,
                },
            )(),
        ]

    monkeypatch.setattr(evaluations, "evaluate_selected_metrics", evaluate_once)
    result = asyncio.run(
        _evaluate_live_row(
            "input",
            "actual",
            "expected",
            0,
            70,
            "deepeval",
            _dynamic_metrics(),
        )
    )

    assert result.score == 74
    assert result.passed is True
    assert [metric.weight_percent for metric in result.metrics] == [60, 40]


def test_run_rows_are_flushed_before_normalized_metric_results() -> None:
    events: list[str] = []

    class Session:
        def add_all(self, items: list[object]) -> None:
            events.append(type(items[0]).__name__ if items else "empty")

        async def flush(self) -> None:
            events.append("flush")

    row = EvaluationRunRow(
        run_id=uuid.uuid4(),
        input="question",
        expected_output="expected answer",
    )
    metric = EvaluationRunMetricResult(
        run_row_id=row.id,
        metric_key="geval_correctness",
        display_name="Correctness (G-Eval)",
        score=80,
        raw_score_ratio=0.8,
        weight_percent=100,
        weighted_score=80,
    )

    asyncio.run(
        _stage_run_evidence(
            cast(Any, Session()),
            [row],
            [metric],
        )
    )

    assert events == ["EvaluationRunRow", "flush", "EvaluationRunMetricResult"]


def test_parse_csv_dataset() -> None:
    rows = parse_dataset(
        "sample.csv",
        b"input,actual_output,expected_output\nhello,world,world\n",
    )

    assert rows == [
        {"input": "hello", "actual_output": "world", "expected_output": "world"}
    ]


def test_exact_match_passes() -> None:
    result = _evaluate_row(
        {
            "input": "greeting",
            "actual_output": " Hello  world ",
            "expected_output": "hello world",
        },
        index=0,
        threshold=70,
    )

    assert result.passed is True
    assert result.score == 100
    assert [metric.reason for metric in result.metrics] == [
        "정규화된 실제 응답과 기대 응답이 일치합니다.",
        "정규화된 응답의 문자 단위 유사도는 100.00점입니다.",
        "기대 응답 토큰 2개 중 2개가 실제 응답에 포함되어 있습니다. (점수 100.00점)",
    ]


def test_import_json_dataset_accepts_data_envelope() -> None:
    rows = _import_rows(
        "dataset.json",
        b'{"data": [{"input": "hello", "expected_output": "world"}]}',
    )

    assert len(rows) == 1
    assert rows[0].input == "hello"


def test_import_json_dataset_rejects_missing_expected_output() -> None:
    with pytest.raises(HTTPException, match="expected_output"):
        _import_rows("dataset.json", b'[{"input": "hello"}]')


def test_saved_run_serializes_metrics_once() -> None:
    run = EvaluationRun(dataset_id=uuid.uuid4(), owner_id=uuid.uuid4())
    row = EvaluationRunRow(
        run_id=run.id,
        input="hello",
        expected_output="world",
        actual_output="world",
        metrics=[{"name": "exact_match", "score": 1.0}],
    )

    result = _saved_run(run, [row])

    assert result.created_at == run.created_at.isoformat()
    assert result.rows[0].metrics[0].name == "exact_match"
    assert (
        result.rows[0].metrics[0].reason
        == "정규화된 실제 응답과 기대 응답이 일치합니다."
    )


def test_saved_run_preserves_deepeval_reason_with_line_breaks() -> None:
    run = EvaluationRun(dataset_id=uuid.uuid4(), owner_id=uuid.uuid4())
    reason = "핵심 내용이 일치합니다.\n표현도 자연스럽습니다."
    row = EvaluationRunRow(
        run_id=run.id,
        input="hello",
        expected_output="world",
        actual_output="world",
        metrics=[{"name": "deepeval_geval", "score": 82.5, "reason": reason}],
    )

    result = _saved_run(run, [row])

    assert result.rows[0].metrics[0].reason == reason


@pytest.mark.parametrize(
    "url", ["http://localhost:9001/chat", "http://127.0.0.1:9001/chat"]
)
def test_local_endpoint_accepts_http_and_loopback_urls(url: str) -> None:
    assert _validate_external_url(url) == url


def test_deepeval_reads_api_key_from_settings_env_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("from-dotenv"))
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: object())

    _require_deepeval()

    assert _openai_api_key() == "from-dotenv"
    assert os.environ["OPENAI_API_KEY"] == "from-dotenv"


def test_create_local_http_endpoint() -> None:
    class Session:
        def __init__(self) -> None:
            self.added: list[EvaluationEndpoint] = []

        def add(self, endpoint: EvaluationEndpoint) -> None:
            self.added.append(endpoint)

        async def commit(self) -> None:
            return None

        async def refresh(self, _endpoint: EvaluationEndpoint) -> None:
            return None

    session = Session()
    endpoint = asyncio.run(
        create_endpoint(
            EvaluationEndpointCreate(
                name="Local ChatOpenAI",
                base_url="http://localhost:9001/chat",
            ),
            cast(Any, session),
            cast(Any, None),
        )
    )

    assert endpoint.base_url == "http://localhost:9001/chat"
    assert session.added[0].base_url == endpoint.base_url


@pytest.mark.parametrize(
    "url",
    ["http://example.com", "https://localhost/api", "https://127.0.0.1/api"],
)
def test_non_local_endpoint_rejects_insecure_or_private_urls(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with pytest.raises(HTTPException):
        _validate_external_url(url)


def test_scenario_url_must_match_allowed_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("8.8.8.8", 443))],
    )
    endpoint = EvaluationEndpoint(name="A", base_url="https://api.example.com")

    assert _assert_url_allowed(endpoint, "https://api.example.com/v1/chat")
    with pytest.raises(HTTPException, match="selected allowed server"):
        _assert_url_allowed(endpoint, "https://other.example.com/v1/chat")


def test_turn_variables_replace_previous_and_identifier_output() -> None:
    result = _replace_variables(
        {"previous": "{{previous_output}}", "first": "{{first_answer}}"},
        {"previous_output": "one", "first_answer": "two"},
    )

    assert result == {"previous": "one", "first": "two"}


def test_turn_variables_inject_structured_conversation_history() -> None:
    history = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
    ]

    result = _replace_variables(
        {"message": "follow up", "history": "{{conversation_history}}"},
        {"conversation_history": history},
    )

    assert result == {"message": "follow up", "history": history}


def test_request_body_supports_user_defined_chat_json() -> None:
    template = """{
      "message": "{{input}}",
      "system_prompt": "Answer briefly",
      "history": [{"role": "user", "content": "Earlier question"}]
    }"""

    body, is_json = _request_body(template, {"input": "Current question"})

    assert is_json is True
    assert body == {
        "message": "Current question",
        "system_prompt": "Answer briefly",
        "history": [{"role": "user", "content": "Earlier question"}],
    }


def test_conversation_user_content_uses_message_instead_of_raw_json() -> None:
    assert (
        _conversation_user_content(
            '{"message":"follow up","history":[{"role":"user","content":"first"}]}'
        )
        == "follow up"
    )


def test_endpoint_headers_are_encrypted_at_rest() -> None:
    encrypted = encrypt_evaluation_headers({"Authorization": "Bearer secret"})

    assert "Bearer secret" not in encrypted
    assert decrypt_evaluation_headers(encrypted) == {"Authorization": "Bearer secret"}


def test_live_requests_are_always_post(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    received_method = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal received_method
        received_method = request.method
        return httpx.Response(200, json={"answer": "ok"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )

    result = asyncio.run(
        _call_endpoint(
            "https://api.example.com/chat",
            {},
            '{"message":"{{input}}"}',
            "answer",
            {"input": "hello"},
        )
    )

    assert received_method == "POST"
    assert result[2] == "ok"


def test_multi_turn_request_injects_run_thread_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    received_body: dict[str, object] = {}
    received_header = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal received_body, received_header
        received_body = dict(json.loads(request.content))
        received_header = request.headers["x-scenario"]
        return httpx.Response(200, json={"answer": "ok"})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )

    result = asyncio.run(
        _call_endpoint(
            "https://api.example.com/chat",
            {"X-Scenario": "multi-turn"},
            '{"message":"hello","thread_id":"user-supplied"}',
            "answer",
            {},
            json_overrides={"thread_id": "run-id"},
        )
    )

    assert received_body == {"message": "hello", "thread_id": "run-id"}
    assert received_header == "multi-turn"
    assert json.loads(result[3])["thread_id"] == "run-id"


def test_scenario_run_serializes_baseline_turn_comparison() -> None:
    run = EvaluationScenarioRun(scenario_id=uuid.uuid4(), owner_id=uuid.uuid4())
    baseline = EvaluationScenarioRunTurn(
        run_id=uuid.uuid4(),
        position=0,
        identifier="answer",
        actual_output="before",
        score=40,
    )
    current = EvaluationScenarioRunTurn(
        run_id=run.id, position=0, identifier="answer", actual_output="after", score=80
    )

    result = _scenario_run(run, [current], [baseline])

    assert result.turns[0].baseline_actual_output == "before"
    assert result.turns[0].output_changed is True
    assert result.turns[0].score_delta == 40
    assert result.overall_score == run.overall_score
    assert result.conversation_score == run.geval_score


def test_create_scenario_rejects_blank_endpoint_id_with_actionable_message() -> None:
    scenario = EvaluationScenarioCreate.model_validate(
        {
            "name": "Missing endpoint",
            "endpoint_id": "",
            "evaluator": "local",
            "turns": [{"identifier": "answer", "url": "https://api.example.com/chat"}],
        }
    )

    with pytest.raises(HTTPException, match="administrator-managed A server") as error:
        asyncio.run(create_scenario(scenario, cast(Any, None), cast(Any, None)))

    assert error.value.status_code == 422


def test_create_scenario_saves_valid_managed_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Session:
        def __init__(self, endpoint: EvaluationEndpoint) -> None:
            self.endpoint = endpoint
            self.added: list[object] = []

        async def get(self, _model: object, _id: uuid.UUID) -> EvaluationEndpoint:
            return self.endpoint

        def add(self, item: object) -> None:
            self.added.append(item)

        def add_all(self, items: list[object]) -> None:
            self.added.extend(items)

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            return None

        async def refresh(self, _item: object) -> None:
            return None

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("8.8.8.8", 443))],
    )
    endpoint = EvaluationEndpoint(name="A", base_url="https://api.example.com")
    scenario = EvaluationScenarioCreate.model_validate(
        {
            "name": "Valid scenario",
            "endpoint_id": str(endpoint.id),
            "evaluator": "local",
            "turns": [{"identifier": "answer", "url": "https://api.example.com/chat"}],
        }
    )
    session = Session(endpoint)
    user = type("User", (), {"id": uuid.uuid4(), "is_superuser": False})()

    saved = asyncio.run(create_scenario(scenario, cast(Any, session), cast(Any, user)))

    assert saved.endpoint_id == endpoint.id
    assert saved.turn_count == 1
