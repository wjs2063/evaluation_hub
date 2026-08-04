# 단일·다중 VM 배포 가이드

## 1. 구조

브라우저의 단일 진입점은 프런트엔드 Nginx다. 운영 UI는 빈
`VITE_API_URL`로 빌드되어 현재 Origin의 `/api/v1/...`을 호출하고,
Nginx가 `BACKEND_UPSTREAM`으로 전달한다. `/docs`와 `/redoc`도 같은
방식으로 전달된다.

```text
브라우저 --HTTPS--> 외부 LB --HTTP--> frontend:80
                                      |
                                      +--HTTP--> backend:8000
                                                    |
                                                    +--TCP--> db:5432
```

외부 LB가 TLS 인증서, HTTP→HTTPS 리다이렉트, 프런트엔드 헬스 체크를
담당한다. VM 사이에는 고정 사설 IP 또는 내부 DNS가 있다고 가정한다.

## 2. 운영 환경변수

각 VM의 `.env`에서 다음 인터페이스를 사용한다.

| 변수 | 의미 | 일반적인 값 |
|---|---|---|
| `COMPOSE_PROFILES` | 이 VM에서 실행할 구성요소 | `db,backend,frontend` |
| `FRONTEND_HOST` | 사용자가 접속하는 공개 HTTPS Origin | `https://admin.example.com` |
| `BACKEND_UPSTREAM` | Nginx가 접근할 백엔드 URL, 후행 `/` 금지 | `http://backend:8000` |
| `POSTGRES_SERVER` | 백엔드가 접근할 DB 서비스명/사설 주소 | `db` |
| `DB_BIND_ADDRESS` | 호스트 5432 바인드 주소 | `127.0.0.1` |
| `BACKEND_BIND_ADDRESS` | 호스트 8000 바인드 주소 | `127.0.0.1` |
| `FRONTEND_BIND_ADDRESS` | 호스트 80 바인드 주소 | `0.0.0.0` 또는 LB 전용 사설 IP |
| `VITE_API_URL` | 브라우저가 직접 호출할 API URL | 운영 기본값은 빈 문자열 |
| `BACKEND_CORS_ORIGINS` | 백엔드를 직접 호출하는 추가 브라우저 Origin | 운영 기본값은 빈 문자열 |

공통 애플리케이션 설정도 기존과 같이 지정한다.

```dotenv
ENVIRONMENT=production
PROJECT_NAME=Admin
STACK_NAME=admin-production

FRONTEND_HOST=https://admin.example.com
VITE_API_URL=
BACKEND_CORS_ORIGINS=

SECRET_KEY=<긴 임의 값>
FIRST_SUPERUSER=admin@example.com
FIRST_SUPERUSER_PASSWORD=<긴 임의 값>

POSTGRES_PORT=5432
POSTGRES_DB=app
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<긴 임의 값>

DOCKER_IMAGE_BACKEND=registry.example.com/admin/backend
DOCKER_IMAGE_FRONTEND=registry.example.com/admin/frontend
TAG=latest
```

`SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD`, `POSTGRES_PASSWORD`는 서로 다른
값을 사용하고 `.env` 권한을 제한한다.

```bash
chmod 600 .env
```

## 3. 배치별 설정

아래 주소는 예시다.

- DB VM: `10.0.0.10`
- Backend VM: `10.0.0.20`
- Frontend VM: `10.0.0.30`

### 모두 같은 VM

```dotenv
COMPOSE_PROFILES=db,backend,frontend
POSTGRES_SERVER=db
BACKEND_UPSTREAM=http://backend:8000
DB_BIND_ADDRESS=127.0.0.1
BACKEND_BIND_ADDRESS=127.0.0.1
FRONTEND_BIND_ADDRESS=0.0.0.0
```

### 모두 다른 VM

DB VM:

```dotenv
COMPOSE_PROFILES=db
DB_BIND_ADDRESS=10.0.0.10
```

Backend VM:

```dotenv
COMPOSE_PROFILES=backend
POSTGRES_SERVER=10.0.0.10
BACKEND_BIND_ADDRESS=10.0.0.20
```

Frontend VM:

```dotenv
COMPOSE_PROFILES=frontend
BACKEND_UPSTREAM=http://10.0.0.20:8000
FRONTEND_BIND_ADDRESS=10.0.0.30
```

### DB + Backend / Frontend

DB·Backend VM:

```dotenv
COMPOSE_PROFILES=db,backend
POSTGRES_SERVER=db
DB_BIND_ADDRESS=127.0.0.1
BACKEND_BIND_ADDRESS=10.0.0.20
```

Frontend VM:

```dotenv
COMPOSE_PROFILES=frontend
BACKEND_UPSTREAM=http://10.0.0.20:8000
FRONTEND_BIND_ADDRESS=10.0.0.30
```

### Backend + Frontend / DB

Backend·Frontend VM:

```dotenv
COMPOSE_PROFILES=backend,frontend
POSTGRES_SERVER=10.0.0.10
BACKEND_UPSTREAM=http://backend:8000
BACKEND_BIND_ADDRESS=127.0.0.1
FRONTEND_BIND_ADDRESS=10.0.0.20
```

DB VM:

```dotenv
COMPOSE_PROFILES=db
DB_BIND_ADDRESS=10.0.0.10
```

### DB + Frontend / Backend

DB·Frontend VM:

```dotenv
COMPOSE_PROFILES=db,frontend
DB_BIND_ADDRESS=10.0.0.10
BACKEND_UPSTREAM=http://10.0.0.20:8000
FRONTEND_BIND_ADDRESS=10.0.0.30
```

Backend VM:

```dotenv
COMPOSE_PROFILES=backend
POSTGRES_SERVER=10.0.0.10
BACKEND_BIND_ADDRESS=10.0.0.20
```

## 4. CORS 규칙

- Origin은 `scheme://host[:port]` 전체가 일치해야 한다.
- 경로, 쿼리, 후행 `/`를 넣지 않는다. 입력된 후행 `/`는 설정 로딩 시
  제거된다.
- 자격 증명을 허용하므로 `*`는 사용할 수 없다.
- 운영 기본값은 `FRONTEND_HOST=https://admin.example.com`,
  `VITE_API_URL=`, `BACKEND_CORS_ORIGINS=`이다.
- 로컬 Vite가 `VITE_API_URL=http://localhost:8000`으로 백엔드를 직접
  호출할 때만 `BACKEND_CORS_ORIGINS=http://localhost:5173`을 추가한다.
- `VITE_API_URL`은 빌드 시 번들에 포함되므로 변경 뒤 프런트 이미지를
  다시 빌드해야 한다.
- `BACKEND_UPSTREAM`은 컨테이너 시작 시 Nginx 설정에 반영되므로 이미지를
  다시 빌드하지 않고 프런트 컨테이너만 재생성하면 된다.

DB 연결과 Nginx→백엔드 연결은 브라우저 요청이 아니므로 CORS 대상이
아니다.

## 5. 방화벽

필요한 방향만 허용한다.

| 출발지 | 목적지 | 포트 |
|---|---|---|
| 외부 LB | Frontend VM | TCP 80 |
| Frontend VM | Backend VM | TCP 8000 |
| Backend VM | DB VM | TCP 5432 |

Backend와 DB 포트는 인터넷에 공개하지 않는다. `0.0.0.0` 바인딩이 필요한
환경이라도 클라우드 보안 그룹과 호스트 방화벽에서 출발지 사설 IP를
제한한다.

## 6. 배포

운영에서는 로컬 개발 override를 제외하기 위해 항상 `-f compose.yml`을
명시한다.

```bash
docker compose -f compose.yml config --quiet
docker compose -f compose.yml build
docker compose -f compose.yml up -d
docker compose -f compose.yml ps
```

원격 레지스트리 이미지를 사용하는 VM은 `build` 대신 `pull`을 사용할 수
있다.

```bash
docker compose -f compose.yml pull
docker compose -f compose.yml up -d
```

`backend` 프로필은 `prestart`도 활성화한다. `prestart`가 DB 연결을
재시도하고 마이그레이션 및 초기 데이터를 처리한 뒤 백엔드가 시작된다.
한 환경에서 마이그레이션을 수행하는 백엔드 배포 단위는 하나만 둔다.

## 7. 설정 변경

백엔드 위치만 바꿀 때:

```bash
docker compose -f compose.yml up -d --force-recreate frontend
```

`VITE_API_URL` 또는 프런트 빌드 변수를 바꿀 때:

```bash
docker compose -f compose.yml build frontend
docker compose -f compose.yml up -d frontend
```

DB 주소나 비밀값을 바꿀 때는 해당 Backend VM에서 `prestart`와 `backend`를
재생성한다.

## 8. 검증

Frontend VM 또는 LB 경로에서 확인한다.

```bash
curl -I http://127.0.0.1/
curl http://127.0.0.1/api/v1/utils/health-check/
curl -I http://127.0.0.1/docs
```

프런트엔드 호스트 포트가 사설 IP에만 바인딩된 경우 `127.0.0.1` 대신 해당
주소를 사용한다. 로그는 다음과 같이 확인한다.

```bash
docker compose -f compose.yml logs --tail=100 prestart
docker compose -f compose.yml logs --tail=100 backend
docker compose -f compose.yml logs --tail=100 frontend
```

외부에서는 공개 HTTPS 주소 하나만 확인한다.

```bash
curl -I https://admin.example.com/
curl https://admin.example.com/api/v1/utils/health-check/
curl -I https://admin.example.com/docs
```
