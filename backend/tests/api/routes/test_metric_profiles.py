import uuid
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.models import User


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


async def test_normal_users_only_see_active_metric_profiles(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    response = await client.get(
        "/api/v1/evaluations/metric-profiles",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    assert all(item["is_active"] for item in response.json()["data"])


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
        json=request,
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    deleted = await client.delete(
        f"/api/v1/evaluations/metric-profiles/{profile_id}",
        headers=superuser_token_headers,
    )
    assert deleted.status_code == 200
