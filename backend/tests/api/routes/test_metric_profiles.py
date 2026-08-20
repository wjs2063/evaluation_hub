import uuid
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.models import CustomMetric, EvaluationMetricProfileItem, User


async def _superuser_headers(db: AsyncSession) -> dict[str, str]:
    user = (
        await db.exec(select(User).where(User.is_superuser == True))  # noqa: E712
    ).first()
    assert user is not None
    token = security.create_access_token(user.id, timedelta(minutes=5))
    return {"Authorization": f"Bearer {token}"}


async def test_seeded_single_turn_profile_is_readable_from_postgres(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    stored_modes = (
        await db.exec(
            text(
                "SELECT DISTINCT evaluation_mode "
                "FROM evaluationmetricprofile ORDER BY evaluation_mode"
            )
        )
    ).all()
    assert all(row[0] in {"single_turn", "multi_turn"} for row in stored_modes)

    response = await client.get(
        "/api/v1/evaluations/metric-profiles",
        params={"evaluation_mode": "single_turn"},
        headers=await _superuser_headers(db),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    assert all(item["evaluation_mode"] == "single_turn" for item in payload["data"])
    assert all(
        sum(metric["weight_percent"] for metric in item["metrics"]) == 100
        for item in payload["data"]
    )


async def test_normal_users_can_read_shared_metric_profiles(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    response = await client.get(
        "/api/v1/evaluations/metric-profiles",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    assert response.json()["count"] >= len(response.json()["data"])


async def test_custom_metric_placeholder_contract_requires_auth_and_is_ordered(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    unauthorized = await client.get(
        "/api/v1/evaluations/custom-metric-placeholder-contracts"
    )
    assert unauthorized.status_code == 401

    response = await client.get(
        "/api/v1/evaluations/custom-metric-placeholder-contracts",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "evaluation_scope": "quick_upload",
                "syntax": "double_curly_lower_snake_case",
                "requires_at_least_one": True,
                "allowed_keys": ["input", "actual_output", "expected_output"],
            },
            {
                "evaluation_scope": "single_turn",
                "syntax": "double_curly_lower_snake_case",
                "requires_at_least_one": True,
                "allowed_keys": ["input", "actual_output", "expected_output"],
            },
            {
                "evaluation_scope": "multi_turn",
                "syntax": "double_curly_lower_snake_case",
                "requires_at_least_one": True,
                "allowed_keys": ["role", "content", "expected_outcome"],
            },
        ],
        "count": 3,
    }


async def test_custom_metric_create_and_update_reject_typed_placeholder_errors(
    client: AsyncClient,
    db: AsyncSession,
    normal_user_token_headers: dict[str, str],
) -> None:
    suffix = uuid.uuid4().hex
    base = {
        "name": f"엄격 검증 {suffix}",
        "description": "API placeholder 오류 검증",
        "evaluation_scope": "single_turn",
        "is_active": True,
    }
    invalid_create = await client.post(
        "/api/v1/evaluations/custom-metrics",
        headers=normal_user_token_headers,
        json={**base, "prompt": "{{role}} 및 {{content}}를 평가하세요."},
    )
    assert invalid_create.status_code == 422
    create_error = invalid_create.json()["detail"][0]
    assert create_error["type"] == "custom_metric_placeholder_not_allowed"
    assert create_error["loc"] == ["body", "prompt"]
    assert create_error["msg"].startswith("single_turn 범위에서 지원하지 않는")
    assert create_error["ctx"] == {
        "evaluation_scope": "single_turn",
        "invalid_tokens": ["role", "content"],
        "allowed_keys": ["input", "actual_output", "expected_output"],
    }
    assert (
        await db.exec(select(CustomMetric).where(CustomMetric.name == base["name"]))
    ).first() is None

    created = await client.post(
        "/api/v1/evaluations/custom-metrics",
        headers=normal_user_token_headers,
        json={**base, "prompt": "{{input}}의 {{actual_output}}을 평가하세요."},
    )
    assert created.status_code == 200
    metric_id = created.json()["id"]

    invalid_update = await client.put(
        f"/api/v1/evaluations/custom-metrics/{metric_id}",
        headers=normal_user_token_headers,
        json={
            **base,
            "prompt": "{{ input }} 문법 오류를 평가하세요.",
            "expected_version": 1,
        },
    )
    assert invalid_update.status_code == 422
    update_error = invalid_update.json()["detail"][0]
    assert update_error["type"] == "custom_metric_placeholder_malformed"
    assert update_error["loc"] == ["body", "prompt"]
    assert update_error["ctx"]["invalid_tokens"] == ["{{ input }}"]
    db.expire_all()
    stored = await db.get(CustomMetric, uuid.UUID(metric_id))
    assert stored is not None
    assert stored.version == 1
    assert stored.prompt == "{{input}}의 {{actual_output}}을 평가하세요."

    deleted = await client.delete(
        f"/api/v1/evaluations/custom-metrics/{metric_id}",
        headers=normal_user_token_headers,
    )
    assert deleted.status_code == 200


async def test_superuser_can_create_update_and_delete_metric_profile(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    superuser_token_headers = await _superuser_headers(db)
    name = f"통합 테스트 프로필 {uuid.uuid4()}"
    request = {
        "name": name,
        "description": "PostgreSQL CRUD 검증",
        "is_active": True,
        "evaluation_mode": "single_turn",
        "metrics": [
            {"metric_type": "exact_match", "weight_percent": 100},
        ],
    }
    created = await client.post(
        "/api/v1/evaluations/metric-profiles",
        headers=superuser_token_headers,
        json=request,
    )
    assert created.status_code == 200
    profile_id = created.json()["id"]

    request["name"] = f"{name} 수정"
    updated = await client.put(
        f"/api/v1/evaluations/metric-profiles/{profile_id}",
        headers=superuser_token_headers,
        json={**request, "expected_version": 1},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    deleted = await client.delete(
        f"/api/v1/evaluations/metric-profiles/{profile_id}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200


async def test_normal_user_custom_metric_crud_snapshot_and_conflicts(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    suffix = uuid.uuid4().hex
    custom_request = {
        "name": f"친절도 {suffix}",
        "description": "공유 CustomMetric",
        "evaluation_scope": "quick_upload",
        "prompt": "{{input}}에 대한 {{actual_output}}의 친절도를 평가하세요.",
        "is_active": True,
    }
    created = await client.post(
        "/api/v1/evaluations/custom-metrics",
        headers=normal_user_token_headers,
        json=custom_request,
    )
    assert created.status_code == 200
    custom = created.json()
    assert custom["version"] == 1
    assert custom["required_keys"] == ["input", "actual_output"]

    stale = await client.put(
        f"/api/v1/evaluations/custom-metrics/{custom['id']}",
        headers=normal_user_token_headers,
        json={**custom_request, "expected_version": 99},
    )
    assert stale.status_code == 409

    profile_request = {
        "name": f"빠른 업로드 {suffix}",
        "description": "CustomMetric 스냅샷",
        "evaluation_scope": "quick_upload",
        "is_active": True,
        "metrics": [
            {
                "custom_metric_id": custom["id"],
                "weight_percent": 100,
                "required_keys": ["role", "client_value_must_be_ignored"],
            },
        ],
    }
    profile_response = await client.post(
        "/api/v1/evaluations/metric-profiles",
        headers=normal_user_token_headers,
        json=profile_request,
    )
    assert profile_response.status_code == 200
    profile = profile_response.json()
    assert profile["evaluation_scope"] == "quick_upload"
    assert profile["evaluation_mode"] == "single_turn"
    assert profile["metrics"][0]["custom_metric_version"] == 1
    assert profile["metrics"][0]["custom_metric_prompt"] == custom_request["prompt"]
    assert profile["metrics"][0]["required_keys"] == ["input", "actual_output"]

    referenced = await client.delete(
        f"/api/v1/evaluations/custom-metrics/{custom['id']}",
        headers=normal_user_token_headers,
    )
    assert referenced.status_code == 409

    deleted_profile = await client.delete(
        f"/api/v1/evaluations/metric-profiles/{profile['id']}",
        headers=normal_user_token_headers,
    )
    assert deleted_profile.status_code == 200
    deleted_custom = await client.delete(
        f"/api/v1/evaluations/custom-metrics/{custom['id']}",
        headers=normal_user_token_headers,
    )
    assert deleted_custom.status_code == 200


async def test_corrupted_custom_metric_snapshot_is_blocked_before_execution(
    client: AsyncClient,
    db: AsyncSession,
    normal_user_token_headers: dict[str, str],
) -> None:
    suffix = uuid.uuid4().hex
    metric_response = await client.post(
        "/api/v1/evaluations/custom-metrics",
        headers=normal_user_token_headers,
        json={
            "name": f"손상 감지 {suffix}",
            "description": "실행 전 재검증",
            "evaluation_scope": "quick_upload",
            "prompt": "{{input}}과 {{actual_output}}을 평가하세요.",
            "is_active": True,
        },
    )
    assert metric_response.status_code == 200
    metric = metric_response.json()
    profile_response = await client.post(
        "/api/v1/evaluations/metric-profiles",
        headers=normal_user_token_headers,
        json={
            "name": f"손상 감지 프로필 {suffix}",
            "description": "실행 전 재검증",
            "evaluation_scope": "quick_upload",
            "is_active": True,
            "metrics": [
                {"custom_metric_id": metric["id"], "weight_percent": 100}
            ],
        },
    )
    assert profile_response.status_code == 200
    profile = profile_response.json()

    item = (
        await db.exec(
            select(EvaluationMetricProfileItem).where(
                EvaluationMetricProfileItem.profile_id == uuid.UUID(profile["id"])
            )
        )
    ).one()
    item.required_keys = ["input", "expected_output"]
    db.add(item)
    await db.commit()

    run = await client.post(
        "/api/v1/evaluations/run",
        headers=normal_user_token_headers,
        data={
            "framework": "deepeval",
            "threshold": "70",
            "metric_profile_id": profile["id"],
        },
        files={
            "file": (
                "evaluation.csv",
                b"input,actual_output,expected_output\nquestion,answer,expected\n",
                "text/csv",
            )
        },
    )
    assert run.status_code == 409
    detail = run.json()["detail"]
    assert metric["name"] in detail
    assert metric["id"] in detail
    assert "required_keys" in detail
    assert "다시 저장" in detail

    await db.delete(item)
    await db.commit()
    deleted_profile = await client.delete(
        f"/api/v1/evaluations/metric-profiles/{profile['id']}",
        headers=normal_user_token_headers,
    )
    assert deleted_profile.status_code == 200
    deleted_metric = await client.delete(
        f"/api/v1/evaluations/custom-metrics/{metric['id']}",
        headers=normal_user_token_headers,
    )
    assert deleted_metric.status_code == 200
