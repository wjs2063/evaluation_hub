import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import engine
from app.cron_schedule import next_cron_run
from app.models import (
    EvaluationJob,
    EvaluationRun,
    EvaluationScenarioRun,
    EvaluationSchedule,
    get_datetime_utc,
)

TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}
logger = logging.getLogger(__name__)


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4()}"


async def enqueue_dataset_job(
    session: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    owner_id: uuid.UUID,
    baseline_run_id: uuid.UUID | None = None,
    schedule_id: uuid.UUID | None = None,
    metric_profile_id: uuid.UUID | None = None,
    scheduled_for: datetime | None = None,
) -> EvaluationJob:
    due_at = scheduled_for or get_datetime_utc()
    job = EvaluationJob(
        dataset_id=dataset_id,
        owner_id=owner_id,
        baseline_run_id=baseline_run_id,
        schedule_id=schedule_id,
        metric_profile_id=metric_profile_id,
        scheduled_for=due_at,
        available_at=due_at,
        max_attempts=settings.EVALUATION_JOB_MAX_ATTEMPTS,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def enqueue_scenario_job(
    session: AsyncSession,
    *,
    scenario_id: uuid.UUID,
    owner_id: uuid.UUID,
    baseline_run_id: uuid.UUID | None = None,
    schedule_id: uuid.UUID | None = None,
    metric_profile_id: uuid.UUID | None = None,
    scheduled_for: datetime | None = None,
) -> EvaluationJob:
    due_at = scheduled_for or get_datetime_utc()
    job = EvaluationJob(
        scenario_id=scenario_id,
        owner_id=owner_id,
        baseline_run_id=baseline_run_id,
        schedule_id=schedule_id,
        metric_profile_id=metric_profile_id,
        scheduled_for=due_at,
        available_at=due_at,
        max_attempts=settings.EVALUATION_JOB_MAX_ATTEMPTS,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def claim_next_job(worker_id: str) -> EvaluationJob | None:
    now = get_datetime_utc()
    lease_until = now + timedelta(seconds=settings.EVALUATION_JOB_LEASE_SECONDS)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.exec(
            update(EvaluationJob)
            .where(
                col(EvaluationJob.status) == "running",
                col(EvaluationJob.lease_expires_at) <= now,
                col(EvaluationJob.attempt) >= col(EvaluationJob.max_attempts),
            )
            .values(
                status="failed",
                error="Worker lease expired after the maximum number of attempts",
                claimed_by=None,
                lease_expires_at=None,
                finished_at=now,
            )
        )
        statement = (
            select(EvaluationJob)
            .where(
                or_(
                    and_(
                        col(EvaluationJob.status) == "queued",
                        col(EvaluationJob.available_at) <= now,
                    ),
                    and_(
                        col(EvaluationJob.status) == "running",
                        col(EvaluationJob.lease_expires_at) <= now,
                        col(EvaluationJob.attempt) < col(EvaluationJob.max_attempts),
                    ),
                )
            )
            .order_by(col(EvaluationJob.available_at), col(EvaluationJob.created_at))
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = (await session.exec(statement)).first()
        if not job:
            await session.commit()
            return None
        job.status = "running"
        job.claimed_by = worker_id
        job.lease_expires_at = lease_until
        job.heartbeat_at = now
        job.started_at = job.started_at or now
        job.finished_at = None
        job.error = None
        job.attempt += 1
        session.add(job)
        await session.commit()
        return job


async def heartbeat_job(job_id: uuid.UUID, worker_id: str) -> bool:
    now = get_datetime_utc()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        result = await session.exec(
            update(EvaluationJob)
            .where(
                col(EvaluationJob.id) == job_id,
                col(EvaluationJob.status) == "running",
                col(EvaluationJob.claimed_by) == worker_id,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now
                + timedelta(seconds=settings.EVALUATION_JOB_LEASE_SECONDS),
            )
        )
        await session.commit()
        return bool(result.rowcount)


async def complete_job(job_id: uuid.UUID, worker_id: str) -> bool:
    now = get_datetime_utc()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        result = await session.exec(
            update(EvaluationJob)
            .where(
                col(EvaluationJob.id) == job_id,
                col(EvaluationJob.status) == "running",
                col(EvaluationJob.claimed_by) == worker_id,
            )
            .values(
                status="succeeded",
                claimed_by=None,
                lease_expires_at=None,
                heartbeat_at=now,
                finished_at=now,
                error=None,
            )
        )
        await session.commit()
        return bool(result.rowcount)


async def fail_or_retry_job(job: EvaluationJob, worker_id: str, error: str) -> str:
    now = get_datetime_utc()
    retry = job.attempt < job.max_attempts
    next_status = "queued" if retry else "failed"
    retry_at = now + timedelta(seconds=min(300, 2 ** max(job.attempt, 1)))
    async with AsyncSession(engine, expire_on_commit=False) as session:
        result = await session.exec(
            update(EvaluationJob)
            .where(
                col(EvaluationJob.id) == job.id,
                col(EvaluationJob.status) == "running",
                col(EvaluationJob.claimed_by) == worker_id,
            )
            .values(
                status=next_status,
                available_at=retry_at if retry else job.available_at,
                claimed_by=None,
                lease_expires_at=None,
                heartbeat_at=now,
                finished_at=None if retry else now,
                error=error[:2000],
            )
        )
        await session.commit()
        if not result.rowcount:
            return "lease_lost"
    return next_status


async def existing_run_id(job_id: uuid.UUID) -> uuid.UUID | None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        dataset_run_id = (
            await session.exec(
                select(EvaluationRun.id).where(EvaluationRun.job_id == job_id)
            )
        ).first()
        if dataset_run_id:
            return dataset_run_id
        return (
            await session.exec(
                select(EvaluationScenarioRun.id).where(
                    EvaluationScenarioRun.job_id == job_id
                )
            )
        ).first()


async def enqueue_due_schedules(limit: int = 100) -> int:
    now = get_datetime_utc()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        schedules = list(
            (
                await session.exec(
                    select(EvaluationSchedule)
                    .where(
                        EvaluationSchedule.is_active == True,  # noqa: E712
                        EvaluationSchedule.next_run_at <= now,
                    )
                    .order_by(col(EvaluationSchedule.next_run_at))
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            ).all()
        )
        for schedule in schedules:
            scheduled_for = schedule.next_run_at
            session.add(
                EvaluationJob(
                    dataset_id=schedule.dataset_id,
                    scenario_id=schedule.scenario_id,
                    owner_id=schedule.owner_id,
                    baseline_run_id=schedule.baseline_run_id,
                    schedule_id=schedule.id,
                    scheduled_for=scheduled_for,
                    available_at=scheduled_for,
                    max_attempts=settings.EVALUATION_JOB_MAX_ATTEMPTS,
                )
            )
            if schedule.schedule_type == "cron":
                if not schedule.cron_expression:
                    raise ValueError("Cron schedule is missing cron_expression")
                next_run = next_cron_run(
                    schedule.cron_expression, now, schedule.timezone
                )
            else:
                if schedule.interval_seconds is None:
                    raise ValueError("Interval schedule is missing interval_seconds")
                next_run = scheduled_for + timedelta(seconds=schedule.interval_seconds)
                while next_run <= now:
                    next_run += timedelta(seconds=schedule.interval_seconds)
            schedule.last_enqueued_at = scheduled_for
            schedule.next_run_at = next_run
            schedule.updated_at = now
            session.add(schedule)
        await session.commit()
        return len(schedules)


async def _heartbeat_loop(
    job_id: uuid.UUID, worker_id: str, stop: asyncio.Event
) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=settings.EVALUATION_JOB_HEARTBEAT_SECONDS
            )
        except TimeoutError:
            if not await heartbeat_job(job_id, worker_id):
                stop.set()


async def execute_claimed_job(job: EvaluationJob, worker_id: str) -> None:
    heartbeat_stop = asyncio.Event()
    heartbeat = asyncio.create_task(
        _heartbeat_loop(job.id, worker_id, heartbeat_stop),
        name=f"heartbeat-{job.id}",
    )
    try:
        if not await existing_run_id(job.id):
            if job.dataset_id:
                from app.api.routes.evaluations import execute_saved_dataset_job

                await execute_saved_dataset_job(job)
            elif job.scenario_id:
                from app.api.routes.evaluations import execute_saved_scenario_job

                await execute_saved_scenario_job(job)
            else:
                raise ValueError("Evaluation job has no target")
        if not await complete_job(job.id, worker_id):
            raise RuntimeError("Evaluation job lease was lost before completion")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await fail_or_retry_job(job, worker_id, str(exc))
    finally:
        heartbeat_stop.set()
        await heartbeat


async def worker_slot(worker_id: str, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            job = await claim_next_job(worker_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Evaluation worker slot could not poll the job queue")
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=settings.EVALUATION_JOB_POLL_SECONDS
                )
            except TimeoutError:
                pass
            continue
        if job:
            await execute_claimed_job(job, worker_id)
            continue
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=settings.EVALUATION_JOB_POLL_SECONDS
            )
        except TimeoutError:
            pass
