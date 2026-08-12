# FastAPI Project - Development

Frontend, FastAPI, worker, scheduler를 Docker 또는 `uv`/`npm`으로 실행하는
전체 절차는 [통합 실행 및 배포 가이드](run_guide.md)를 참고하세요.

## Docker Compose

The checked-in `.env` enables the `db`, `backend`, and `frontend` profiles for
local development. Start the stack with:

```bash
docker compose watch
```

Local URLs:

- Frontend: <http://localhost:5173>
- API through the frontend Nginx proxy: <http://localhost:5173/api/v1>
- API directly: <http://localhost:8000>
- Swagger UI through Nginx: <http://localhost:5173/docs>
- ReDoc through Nginx: <http://localhost:5173/redoc>
- Adminer: <http://localhost:8080>
- MailCatcher: <http://localhost:1080>

The first startup can take a minute while PostgreSQL becomes ready and
`prestart` applies migrations and creates initial data. Inspect it with:

```bash
docker compose logs -f prestart backend frontend
```

`adminer` and `mailcatcher` exist only in `compose.override.yml`; they are not
part of production deployments that explicitly use `-f compose.yml`.

## Local frontend development

For fast frontend iteration, stop the container and run Vite:

```bash
docker compose stop frontend
cd frontend
bun run dev
```

Vite does not use the container Nginx proxy. To call the backend directly,
create `frontend/.env` with:

```dotenv
VITE_API_URL=http://localhost:8000
```

The root `.env` already allows `http://localhost:5173` in
`BACKEND_CORS_ORIGINS`. Restart Vite after changing `VITE_API_URL`; it is a
build-time value.

## Local backend development

Stop the backend container, keep PostgreSQL running, and start FastAPI on the
host:

```bash
docker compose stop backend
cd backend
fastapi dev
```

The root `.env` uses `POSTGRES_SERVER=localhost` for this workflow. The local
Compose override changes it to `db` only inside the backend containers.

## Compose files and profiles

`compose.yml` is the production definition. It assigns the `db`, `backend`, and
`frontend` profiles and supports selecting any combination with
`COMPOSE_PROFILES`. `compose.override.yml` is loaded automatically for local
development and changes ports, reload settings, and local test services.

Use the production definition explicitly when checking deployment settings:

```bash
docker compose -f compose.yml config --quiet
```

See [deployment.md](deployment.md) and [deploy_guide.md](deploy_guide.md) for
single-VM and split-VM configurations.

## Pre-commit checks

Install and run the configured checks from the repository root:

```bash
uv run prek install -f
uv run prek run --all-files
```
