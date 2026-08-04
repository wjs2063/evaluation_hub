# EvalHub

AI 응답 데이터셋을 업로드하고 평가 결과를 확인하는 모놀리식 웹 애플리케이션입니다. `wjs2063/fullstack`의 FastAPI + React 구성을 기반으로 하며, 소스만 가져와 이 저장소에서 독립적으로 관리합니다.

## 현재 제공하는 기능

- JWT 기반 회원가입·로그인과 사용자 관리
- CSV/JSON 평가 데이터셋 업로드(최대 5MB)
- Exact match, 문자열 유사도, token recall 기반 로컬 평가
- 통과 기준 설정, 평균 점수·통과율·행별 결과 확인
- DeepEval 및 Langfuse 연결을 위한 API/UI 어댑터 경계

DeepEval과 Langfuse는 아직 자격증명 및 모델 연결 전 단계입니다. 현재는 외부 API 키 없이 동작하는 `local` evaluator가 기본값이며, 외부 evaluator 선택 시 명시적으로 미구현 응답을 반환합니다.

## 프로젝트 구조

```text
evaluation_hub/
├── backend/            # FastAPI API, SQLModel, Alembic, pytest
├── frontend/           # React, TypeScript, Vite, TanStack Router
├── examples/           # 바로 업로드할 수 있는 샘플 데이터셋
├── compose.yml         # PostgreSQL + Backend + Frontend
└── .env.sample         # 로컬 환경 변수 템플릿
```

## 실행

Docker가 실행 중인 환경에서 저장소 루트에서 다음 명령을 사용합니다.

```bash
cp .env.sample .env
docker compose up --build
```

- 웹: <http://localhost>
- API 문서: <http://localhost/docs>
- 초기 관리자: `admin@example.com` / `changethis`

로컬 기본 비밀번호와 `SECRET_KEY`는 개발 전용입니다. 외부에 배포하기 전 `.env` 값을 반드시 교체하세요.

로그인 후 사이드바의 **Evaluations**에서 [`examples/sample-evaluation.csv`](examples/sample-evaluation.csv)를 업로드하면 즉시 결과를 확인할 수 있습니다.

## 데이터셋 형식

CSV 헤더 또는 JSON 객체에 다음 세 필드가 필요합니다.

| 필드 | 설명 |
| --- | --- |
| `input` | 모델에 전달한 질문/입력 |
| `actual_output` | 모델이 실제 생성한 응답 |
| `expected_output` | 기대 응답 또는 정답 |

JSON은 객체 배열 또는 `{ "data": [...] }` 형식을 지원합니다.

## 다음 확장 지점

1. `backend/app/api/routes/evaluations.py`의 framework 분기를 service/adapter 계층으로 이동
2. DeepEval metric과 judge model 설정 추가
3. Langfuse dataset/run/score 동기화 및 trace 링크 제공
4. 평가 실행과 행별 결과를 PostgreSQL에 영속화
5. 대용량 작업을 비동기 worker로 분리
