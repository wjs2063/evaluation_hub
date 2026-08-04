import asyncio
import time
from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
from fastapi import BackgroundTasks
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_db
from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.main import app
from app.utils import logger, send_test_email

pytestmark = pytest.mark.anyio


async def test_concurrent_requests_use_independent_sessions(
    client: AsyncClient, superuser_token_headers: dict[str, str]
) -> None:
    sessions: list[AsyncSession] = []

    async def tracked_get_db() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            sessions.append(session)
            yield session

    app.dependency_overrides[get_db] = tracked_get_db
    try:
        responses = await asyncio.gather(
            *(
                client.get(
                    f"{settings.API_V1_STR}/users/me",
                    headers=superuser_token_headers,
                )
                for _ in range(5)
            )
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert all(response.status_code == 200 for response in responses)
    assert len(sessions) == 5
    assert len({id(session) for session in sessions}) == 5


async def test_password_hashing_does_not_block_event_loop() -> None:
    def slow_hash(_password: str) -> str:
        time.sleep(0.05)
        return "hashed"

    with patch.object(security, "get_password_hash", slow_hash):
        hash_task = asyncio.create_task(security.get_password_hash_async("secret"))
        await asyncio.sleep(0.01)
        assert not hash_task.done()
        assert await hash_task == "hashed"


async def test_email_endpoint_registers_background_task(
    client: AsyncClient, superuser_token_headers: dict[str, str]
) -> None:
    email_to = "background@example.com"
    with patch.object(BackgroundTasks, "add_task") as add_task:
        response = await client.post(
            f"{settings.API_V1_STR}/utils/test-email/",
            headers=superuser_token_headers,
            params={"email_to": email_to},
        )

    assert response.status_code == 201
    add_task.assert_called_once_with(send_test_email, email_to=email_to)


async def test_background_email_failure_is_logged() -> None:
    email_to = "failure@example.com"
    with (
        patch("app.utils.generate_test_email", side_effect=RuntimeError("SMTP down")),
        patch.object(logger, "exception") as log_exception,
    ):
        send_test_email(email_to=email_to)

    log_exception.assert_called_once_with("Failed to send email to %s", email_to)
