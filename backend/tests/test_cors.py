import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.config import Settings

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="session")
def db() -> None:
    """Override the global database fixture; CORS preflights do not use the DB."""


def make_settings(
    *,
    frontend_host: str = "http://localhost:5173",
    backend_cors_origins: list[str] | str = "",
) -> Settings:
    return Settings(
        PROJECT_NAME="CORS test",
        SECRET_KEY="test-secret",
        FIRST_SUPERUSER="admin@example.com",
        FIRST_SUPERUSER_PASSWORD="test-password",
        POSTGRES_SERVER="localhost",
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD="test-password",
        POSTGRES_DB="app",
        FRONTEND_HOST=frontend_host,
        BACKEND_CORS_ORIGINS=backend_cors_origins,
    )


def test_cors_origins_are_normalized_and_deduplicated() -> None:
    test_settings = make_settings(
        frontend_host="https://admin.example.com/",
        backend_cors_origins=("https://direct.example.com/,https://admin.example.com/"),
    )

    assert test_settings.FRONTEND_HOST == "https://admin.example.com"
    assert test_settings.all_cors_origins == [
        "https://direct.example.com",
        "https://admin.example.com",
    ]


@pytest.mark.parametrize(
    "origin",
    ["*", "https://admin.example.com/path", "https://admin.example.com?debug=1"],
)
def test_cors_origins_reject_non_origins(origin: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(backend_cors_origins=origin)


async def test_registered_origin_preflight_is_allowed(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/utils/health-check/",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_unregistered_origin_preflight_is_rejected(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/utils/health-check/",
        headers={
            "Origin": "https://unregistered.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
