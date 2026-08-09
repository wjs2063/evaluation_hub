# ChatOpenAI FastAPI 예제 서버

`message`를 ChatOpenAI에 전달하고, 평가 워크스페이스의 기본 응답 경로와 같은
`answer` 필드로 응답하는 독립 FastAPI 서버입니다.

## 실행

```bash
cd examples/chat-openai-server
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="gpt-4.1-mini" # 선택 사항
uv run fastapi dev main.py
```

기본적으로 프로젝트 루트 `.env`의 `POSTGRES_SERVER`, `POSTGRES_PORT`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`를 읽어 현재 Evaluation Hub
DB를 checkpoint 저장소로 사용합니다. 별도 DB를 사용할 때만 아래 값을 지정하세요.

```bash
export CHECKPOINT_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/app?sslmode=disable"
```

서버는 기본적으로 `http://127.0.0.1:8000`에서 시작합니다.

```bash
curl http://127.0.0.1:8000/chat \
  -H 'content-type: application/json' \
  -d '{"message":"FastAPI가 무엇인가요?"}'
```

응답 예시:

```json
{"answer":"..."}
```

같은 `thread_id`를 사용하면 이전 대화가 PostgreSQL checkpoint에서 자동으로
복원됩니다. `history`는 해당 thread의 첫 요청에서만 초기 대화로 저장됩니다.

```json
{
  "thread_id": "user-123-conversation-1",
  "message": "그 조건을 유지하면서 다음 단계를 알려줘",
  "history": [
    { "role": "user", "content": "첫 질문" },
    { "role": "assistant", "content": "첫 답변" }
  ]
}
```

예를 들어 첫 요청에서 이름을 알려준 뒤 같은 `thread_id`로 다시 질문하면 됩니다.

```bash
curl http://127.0.0.1:8000/chat \
  -H 'content-type: application/json' \
  -d '{"thread_id":"demo-1","message":"내 이름은 재현이야."}'

curl http://127.0.0.1:8000/chat \
  -H 'content-type: application/json' \
  -d '{"thread_id":"demo-1","message":"내 이름이 뭐였지?"}'
```

서버 시작 시 LangGraph가 checkpoint 테이블을 자동으로 준비합니다. 실제 서비스에서는
사용자와 대화마다 추측하기 어려운 고유 `thread_id`를 사용해 대화를 분리하세요.

## EvalHub에 연결

로컬 EvalHub에서는 관리자 화면에 `http://localhost:9001/chat`을 A 서버로 등록하고,
시나리오의 turn URL도 동일하게 입력하면 됩니다. EvalHub 백엔드를 Docker로 실행 중인
macOS 환경이라면 컨테이너에서 호스트로 접근할 수 있도록
`http://host.docker.internal:9001/chat`을 사용합니다. staging/production 환경에서는
HTTPS와 외부에서 접근 가능한 호스트만 허용됩니다.

두 번째 이후 turn의 요청 JSON에는 EvalHub가 누적한 히스토리를 넣을 수
있습니다. 아래 플레이스홀더를 문자열 전체 값으로 사용하면 실제 JSON 배열로
치환됩니다.

```json
{"message":"후속 질문","history":"{{conversation_history}}"}
```
