# Frontend · Backend 실행 및 배포 가이드

이 문서는 EvaluationHub의 웹 UI, FastAPI API, 평가 worker, scheduler를
Docker 또는 로컬 프로세스로 실행하는 방법을 설명한다. 모든 명령은 별도
표기가 없으면 저장소 루트에서 실행한다.

## 1. 구성요소

| 구성요소 | 역할 | 기본 포트 |
|---|---|---:|
| `frontend` | React 정적 파일을 제공하고 `/api`, `/docs`, `/redoc`을 backend로 프록시하는 Nginx | Docker 로컬 `5173`, 운영 `80` |
| `backend` | FastAPI API | `8000` |
| `worker` | DB queue의 평가 및 테스트 job 실행 | 없음 |
| `scheduler` | 등록된 스케줄을 확인하고 실행할 job을 DB queue에 추가 | 없음 |
| `prestart` | DB 연결 확인, Alembic migration, 최초 관리자 데이터 생성 | 없음 |
| `db` | PostgreSQL/PostGIS | `5432` |

API, worker, scheduler는 같은 backend 이미지와 `.env` 설정을 사용한다.
스케줄을 실제로 실행하려면 세 프로세스를 모두 실행해야 한다.

## 2. 환경변수 준비

처음 한 번 샘플을 복사한다.

```bash
cp .env.sample .env
```

최소한 다음 값을 환경에 맞게 확인한다.

```dotenv
FRONTEND_HOST=http://localhost:5173
VITE_API_URL=
BACKEND_UPSTREAM=http://backend:8000

POSTGRES_SERVER=localhost
POSTGRES_PORT=5432
POSTGRES_DB=app
POSTGRES_USER=postgres
POSTGRES_PASSWORD=changethis

EVALUATION_WORKER_CONCURRENCY=4
EVALUATION_JOB_POLL_SECONDS=1
EVALUATION_JOB_LEASE_SECONDS=300
EVALUATION_JOB_HEARTBEAT_SECONDS=30
EVALUATION_JOB_MAX_ATTEMPTS=3
EVALUATION_SCHEDULER_POLL_SECONDS=5

DEEPEVAL_MODEL=gpt-4.1-mini
OPENAI_API_KEY=
```

`EVALUATION_WORKER_CONCURRENCY`는 worker 프로세스 하나가 동시에 실행할 수
있는 job 수이며 허용 범위는 `1`~`4`다. 하나의 job 안에서 사용자가 선택한
평가지표는 순차 실행된다. DeepEval 지표를 사용하려면 `OPENAI_API_KEY`와
`DEEPEVAL_MODEL`을 실제 judge 환경에 맞게 설정한다.

staging/production에서는 `SECRET_KEY`, `POSTGRES_PASSWORD`,
`FIRST_SUPERUSER_PASSWORD`의 기본값을 반드시 교체한다. `.env`는 Git에
커밋하지 않는다.

## 3. Docker로 전체 로컬 실행

로컬에서는 `compose.override.yml`이 자동 적용된다. 따라서 frontend는
`http://localhost:5173`, backend는 `http://localhost:8000`으로 노출된다.

캐시 없이 이미지를 빌드하고 전체 서비스를 시작한다.

```bash
docker compose --profile db --profile backend --profile frontend build --pull --no-cache
docker compose --profile db --profile backend --profile frontend up -d --force-recreate
```

`backend` 프로필은 `prestart`, `backend`, `worker`, `scheduler`를 모두
활성화한다. `prestart`가 migration과 초기 데이터 생성을 완료한 뒤 나머지
backend 서비스가 시작된다.

상태와 로그를 확인한다.

```bash
docker compose ps
docker compose logs --tail=200 prestart backend worker scheduler frontend
```

접속 주소는 다음과 같다.

- 웹 UI: <http://localhost:5173>
- API health check: <http://localhost:8000/api/v1/utils/health-check/>
- Swagger UI: <http://localhost:5173/docs>
- Adminer: <http://localhost:8080>
- MailCatcher: <http://localhost:1080>

코드를 수정하면서 Docker로 개발하려면 다음 명령을 사용할 수 있다.

```bash
docker compose --profile db --profile backend --profile frontend watch
```

## 4. uv와 npm으로 로컬 실행

DB만 Docker로 띄우고 애플리케이션 프로세스는 호스트에서 실행하는 구성을
권장한다. 이때 루트 `.env`의 `POSTGRES_SERVER`는 `localhost`여야 한다.

### 4.1 PostgreSQL 시작

```bash
docker compose --profile db up -d db
docker compose ps db
```

### 4.2 Backend 의존성 및 DB 초기화

```bash
uv sync --package app --group dev
cd backend
uv run alembic upgrade head
uv run python app/initial_data.py
cd ..
```

### 4.3 Backend API, worker, scheduler 시작

각 명령을 저장소 루트 기준 별도 터미널에서 실행한다.

터미널 1 — FastAPI:

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

터미널 2 — 평가 worker:

```bash
cd backend
uv run python -m app.worker
```

터미널 3 — scheduler:

```bash
cd backend
uv run python -m app.scheduler
```

API만 확인하는 경우 worker와 scheduler를 생략할 수 있지만, UI에서 제출한
평가 job과 등록한 스케줄은 처리되지 않는다.

### 4.4 Frontend 시작

Vite 개발 서버는 `/api`, `/docs`, `/redoc`을 backend로 프록시한다.
`frontend/.env.local`을 다음처럼 두면 브라우저는 같은 origin을 사용하므로
별도 CORS 호출을 피할 수 있다.

```dotenv
VITE_API_URL=
VITE_DEV_API_URL=http://127.0.0.1:8000
```

그다음 frontend를 실행한다.

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

웹 UI는 <http://127.0.0.1:5173>에서 접속한다. `VITE_API_URL`을
`http://localhost:8000`처럼 지정해 browser가 backend를 직접 호출하게 할
수도 있지만, 이 경우 그 frontend origin을 루트 `.env`의
`BACKEND_CORS_ORIGINS`에 정확히 추가하고 backend를 재시작해야 한다.

## 5. Docker 운영 배포 (`--no-cache`)

운영에서는 로컬 override가 섞이지 않도록 모든 명령에 `-f compose.yml`을
명시한다. 단일 VM에서 DB, backend, frontend를 함께 운영하는 예시는 다음과
같다.

```dotenv
ENVIRONMENT=production
COMPOSE_PROFILES=db,backend,frontend
POSTGRES_SERVER=db
BACKEND_UPSTREAM=http://backend:8000
FRONTEND_HOST=https://eval.example.com
VITE_API_URL=
BACKEND_CORS_ORIGINS=
```

설정을 검증하고 backend/frontend 이미지를 캐시 없이 빌드한다.

```bash
docker compose -f compose.yml --profile db --profile backend --profile frontend config --quiet
docker compose -f compose.yml --profile backend --profile frontend build --pull --no-cache prestart backend worker scheduler frontend
```

전체 서비스를 시작하거나 새 이미지로 재생성한다.

```bash
docker compose -f compose.yml --profile db --profile backend --profile frontend up -d --force-recreate
docker compose -f compose.yml ps
```

외부 PostgreSQL을 사용한다면 `POSTGRES_SERVER`를 해당 사설 주소로 지정하고
`--profile db`를 제외한다.

```bash
docker compose -f compose.yml --profile backend --profile frontend up -d --force-recreate
```

운영 browser 요청은 빈 `VITE_API_URL`을 사용해 frontend Nginx의 동일 origin
프록시를 거치게 하는 것이 기본이다. 이 구성에서는 backend를 인터넷에 직접
노출할 필요가 없다. TLS와 HTTP→HTTPS redirect는 frontend 앞단의 load
balancer 또는 reverse proxy에서 처리한다.

## 6. Worker 확장

프로세스 하나의 동시 job 수는 최대 4다. 부하가 증가하면 프로세스당 값을
4보다 높이는 대신 worker replica를 늘린다.

```bash
docker compose -f compose.yml --profile backend up -d --scale worker=3 worker
```

위 예시는 최대 `3 × EVALUATION_WORKER_CONCURRENCY`개의 job을 동시에 처리한다.
job claim은 DB lease를 사용하므로 여러 worker가 같은 job을 동시에 처리하지
않는다. scheduler는 중복 방지 계약이 있지만 일반 운영에서는 1개 replica를
유지한다.

## 7. 재배포와 점검

backend 코드만 변경한 경우:

```bash
docker compose -f compose.yml --profile backend build --pull --no-cache prestart backend worker scheduler
docker compose -f compose.yml --profile backend up -d --force-recreate prestart backend worker scheduler
```

frontend 코드 또는 `VITE_API_URL`을 변경한 경우:

```bash
docker compose -f compose.yml --profile frontend build --pull --no-cache frontend
docker compose -f compose.yml --profile frontend up -d --force-recreate frontend
```

로그와 health check:

```bash
docker compose -f compose.yml logs --tail=200 prestart backend worker scheduler frontend
curl -fsS http://127.0.0.1:8000/api/v1/utils/health-check/
curl -I http://127.0.0.1/
```

호스트 포트를 다른 주소에 바인딩했다면 `curl` 주소도 그에 맞게 바꾼다.
평가 요청이 `queued` 상태에 머물면 worker 로그를, 예약 실행이 생성되지 않으면
scheduler 로그와 활성화된 스케줄 시간을 우선 확인한다.

멀티 VM 네트워크와 방화벽 구성은 [deploy_guide.md](deploy_guide.md)를 함께
참고한다.
