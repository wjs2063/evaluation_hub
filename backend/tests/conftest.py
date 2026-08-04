from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from app.models import Item, User
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


@pytest.fixture(scope="session", autouse=True)
async def db(anyio_backend: str) -> AsyncGenerator[AsyncSession]:
    assert anyio_backend == "asyncio"
    async with AsyncSession(engine, expire_on_commit=False) as session:
        existing_item_ids = set((await session.exec(select(Item.id))).all())
        existing_user_ids = set((await session.exec(select(User.id))).all())
        await init_db(session)
        yield session

        item_cleanup = delete(Item)
        if existing_item_ids:
            item_cleanup = item_cleanup.where(col(Item.id).not_in(existing_item_ids))
        await session.exec(item_cleanup)

        user_cleanup = delete(User)
        if existing_user_ids:
            user_cleanup = user_cleanup.where(col(User.id).not_in(existing_user_ids))
        await session.exec(user_cleanup)
        await session.commit()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
async def client() -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture(scope="session")
async def superuser_token_headers(client: AsyncClient) -> dict[str, str]:
    return await get_superuser_token_headers(client)


@pytest.fixture(scope="session")
async def normal_user_token_headers(
    client: AsyncClient, db: AsyncSession
) -> dict[str, str]:
    return await authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
