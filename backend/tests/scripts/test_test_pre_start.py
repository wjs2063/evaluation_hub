from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import select

from app.tests_pre_start import init, logger

pytestmark = pytest.mark.anyio


async def test_init_successful_connection() -> None:
    engine_mock = MagicMock()

    session_mock = MagicMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)
    session_mock.exec = AsyncMock()

    select1 = select(1)

    with (
        patch("app.tests_pre_start.AsyncSession", return_value=session_mock),
        patch("app.tests_pre_start.select", return_value=select1),
        patch.object(logger, "info"),
        patch.object(logger, "error"),
        patch.object(logger, "warn"),
    ):
        try:
            await init(engine_mock)
            connection_successful = True
        except Exception:
            connection_successful = False

        assert connection_successful, (
            "The database connection should be successful and not raise an exception."
        )

        session_mock.exec.assert_awaited_once_with(select1)
