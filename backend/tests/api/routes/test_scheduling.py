import io
import json
import uuid

import pytest
from fastapi import HTTPException, UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.routes.evaluations import (
    create_global_evaluation_schedule,
    delete_global_evaluation_schedule,
    export_multi_turn_dataset,
    export_single_turn_dataset,
    import_scenario,
    import_single_turn_dataset,
    read_all_evaluation_schedules,
    read_datasets,
    read_scenarios,
    update_dataset,
    update_global_evaluation_schedule,
)
from app.models import (
    EvaluationDataset,
    EvaluationDatasetUpdate,
    EvaluationEndpoint,
    EvaluationScenario,
    EvaluationScenarioTurn,
    EvaluationSchedule,
    EvaluationScheduleCreate,
    EvaluationScheduleTargetType,
    EvaluationScheduleType,
    EvaluationScheduleUpdate,
    User,
)


@pytest.mark.anyio
async def test_typed_dataset_upload_export_and_audit_fields(db: AsyncSession) -> None:
    suffix = uuid.uuid4().hex
    owner = User(email=f"dataset-owner-{suffix}@example.com", hashed_password="unused")
    admin = User(
        email=f"dataset-admin-{suffix}@example.com",
        hashed_password="unused",
        is_superuser=True,
    )
    db.add_all([owner, admin])
    await db.flush()
    endpoint = EvaluationEndpoint(
        name="JSON 테스트 서버",
        base_url="https://example.com/chat",
        is_active=True,
    )
    db.add(endpoint)
    await db.commit()

    single_payload = {
        "name": "case별 싱글턴",
        "description": "각 case의 요청과 파싱 규칙",
        "test_type": "single_turn",
        "endpoint_id": str(endpoint.id),
        "metric_profile_id": None,
        "threshold": 0.7,
        "evaluator": "local",
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
    single = await import_single_turn_dataset(
        UploadFile(
            filename="single.json",
            file=io.BytesIO(json.dumps(single_payload).encode()),
        ),
        db,
        owner,
    )
    assert single.created_by_id == owner.id
    assert single.updated_by_id == owner.id
    assert single.rows[0].request_body == '{"message": "질문"}'
    single_export = await export_single_turn_dataset(single.id, db, owner)
    exported_single = json.loads(bytes(single_export.body).decode())
    assert exported_single["test_type"] == "single_turn"
    assert (
        exported_single["cases"][0]["request"]["actual_output_json_pointer"]
        == "/data/answer"
    )

    updated = await update_dataset(
        single.id,
        EvaluationDatasetUpdate(description="관리자 수정"),
        db,
        admin,
    )
    assert updated.created_by_id == owner.id
    assert updated.updated_by_id == admin.id
    assert updated.updated_at >= updated.created_at

    multi_payload = {
        "name": "멀티턴",
        "test_type": "multi_turn",
        "endpoint_id": str(endpoint.id),
        "threshold": 0.7,
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
    multi = await import_scenario(
        UploadFile(
            filename="multi.json",
            file=io.BytesIO(json.dumps(multi_payload).encode()),
        ),
        db,
        owner,
    )
    assert multi.created_by_id == owner.id
    multi_export = await export_multi_turn_dataset(multi.id, db, owner)
    exported_multi = json.loads(bytes(multi_export.body).decode())
    assert exported_multi["test_type"] == "multi_turn"
    assert exported_multi["cases"][0]["request"]["body"] == {"message": "첫 질문"}

    await db.delete(await db.get(EvaluationDataset, single.id))
    await db.delete(await db.get(EvaluationScenario, multi.id))
    await db.flush()
    await db.delete(endpoint)
    await db.delete(owner)
    await db.delete(admin)
    await db.commit()


@pytest.mark.anyio
async def test_schedule_list_and_crud_respect_owner_and_admin(
    db: AsyncSession,
) -> None:
    suffix = uuid.uuid4().hex
    owner = User(
        email=f"schedule-owner-{suffix}@example.com",
        hashed_password="unused",
    )
    other = User(
        email=f"schedule-other-{suffix}@example.com",
        hashed_password="unused",
    )
    admin = User(
        email=f"schedule-admin-{suffix}@example.com",
        hashed_password="unused",
        is_superuser=True,
    )
    db.add_all([owner, other, admin])
    await db.flush()
    owner_dataset = EvaluationDataset(
        name="소유자 데이터셋",
        owner_id=owner.id,
        endpoint_url="https://example.com/evaluate",
        body_template="{}",
    )
    other_dataset = EvaluationDataset(
        name="다른 사용자 데이터셋",
        owner_id=other.id,
        endpoint_url="https://example.com/evaluate",
        body_template="{}",
    )
    db.add_all([owner_dataset, other_dataset])
    await db.flush()
    endpoint = EvaluationEndpoint(
        name="스케줄 테스트 서버",
        base_url="https://example.com",
        is_active=True,
    )
    db.add(endpoint)
    await db.flush()
    scenario = EvaluationScenario(
        name="스케줄 멀티턴",
        owner_id=owner.id,
        endpoint_id=endpoint.id,
        evaluator="local",
    )
    db.add(scenario)
    await db.flush()
    db.add(
        EvaluationScenarioTurn(
            scenario_id=scenario.id,
            position=0,
            identifier="first",
            url="https://example.com/chat",
            body_template='{"message":"hello"}',
            expected_output="hello",
        )
    )
    await db.commit()
    owner_schedule = EvaluationSchedule(
        name="소유자 스케줄",
        dataset_id=owner_dataset.id,
        owner_id=owner.id,
        interval_seconds=3600,
    )
    other_schedule = EvaluationSchedule(
        name="다른 사용자 스케줄",
        dataset_id=other_dataset.id,
        owner_id=other.id,
        interval_seconds=3600,
    )
    db.add_all([owner_schedule, other_schedule])
    await db.commit()

    try:
        single_turn_datasets = await read_datasets(db, owner, 0, 20)
        multi_turn_datasets = await read_scenarios(db, owner, 0, 20)
        assert [item.id for item in single_turn_datasets.data] == [owner_dataset.id]
        assert all(
            item.evaluation_type == "single_turn" for item in single_turn_datasets.data
        )
        assert all(item.test_type == "single_turn" for item in single_turn_datasets.data)
        assert [item.id for item in multi_turn_datasets.data] == [scenario.id]
        assert all(
            item.evaluation_type == "multi_turn" for item in multi_turn_datasets.data
        )
        assert all(item.test_type == "multi_turn" for item in multi_turn_datasets.data)

        own_page = await read_all_evaluation_schedules(db, owner, 0, 20)
        admin_page = await read_all_evaluation_schedules(db, admin, 0, 1)
        assert own_page.count == 1
        assert [item.id for item in own_page.data] == [owner_schedule.id]
        assert admin_page.count >= 2
        assert len(admin_page.data) == 1

        cron_schedule = await create_global_evaluation_schedule(
            EvaluationScheduleCreate(
                name="평일 멀티턴 Cron",
                target_type=EvaluationScheduleTargetType.MULTI_TURN,
                target_id=scenario.id,
                schedule_type=EvaluationScheduleType.CRON,
                cron_expression="0 9 * * 1-5",
                timezone="Asia/Seoul",
            ),
            db,
            owner,
        )
        assert cron_schedule.target_type == EvaluationScheduleTargetType.MULTI_TURN
        assert cron_schedule.scenario_id == scenario.id
        assert cron_schedule.interval_seconds is None
        assert cron_schedule.cron_expression == "0 9 * * 1-5"

        with pytest.raises(HTTPException) as denied:
            await update_global_evaluation_schedule(
                other_schedule.id,
                EvaluationScheduleUpdate(name="권한 없는 수정"),
                db,
                owner,
            )
        assert denied.value.status_code == 403

        updated = await update_global_evaluation_schedule(
            owner_schedule.id,
            EvaluationScheduleUpdate(name="수정된 스케줄", is_active=False),
            db,
            owner,
        )
        assert updated.name == "수정된 스케줄"
        assert updated.is_active is False

        await delete_global_evaluation_schedule(other_schedule.id, db, admin)
        assert await db.get(EvaluationSchedule, other_schedule.id) is None
    finally:
        remaining = await db.get(EvaluationSchedule, owner_schedule.id)
        if remaining:
            await db.delete(remaining)
        for dataset in (owner_dataset, other_dataset):
            remaining_dataset = await db.get(EvaluationDataset, dataset.id)
            if remaining_dataset:
                await db.delete(remaining_dataset)
        remaining_scenario = await db.get(EvaluationScenario, scenario.id)
        if remaining_scenario:
            await db.delete(remaining_scenario)
            await db.flush()
        remaining_endpoint = await db.get(EvaluationEndpoint, endpoint.id)
        if remaining_endpoint:
            await db.delete(remaining_endpoint)
        for test_user in (owner, other, admin):
            remaining_user = await db.get(User, test_user.id)
            if remaining_user:
                await db.delete(remaining_user)
        await db.commit()
