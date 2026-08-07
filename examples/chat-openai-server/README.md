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

멀티턴에서는 이전 `user`/`assistant` 메시지를 `history`로 함께 보냅니다.

```json
{
  "message": "그 조건을 유지하면서 다음 단계를 알려줘",
  "history": [
    { "role": "user", "content": "첫 질문" },
    { "role": "assistant", "content": "첫 답변" }
  ]
}
```

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
