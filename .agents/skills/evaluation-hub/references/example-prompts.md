# Example prompts

## Full-stack evaluation features

```text
$evaluation-hub 데이터셋 실행에 새 평가 metric을 추가하고 행별 reason과 집계 결과를 프런트엔드까지 보여줘.
```

```text
$evaluation-hub 멀티턴 regression에서 baseline과 비교해 점수가 하락한 turn을 명확히 표시해줘.
```

```text
$evaluation-hub Langfuse integration을 설계해줘. 현재 unavailable 상태와 secret 처리 경계를 보존해줘.
```

## Frontend

```text
$evaluation-hub 단일턴 Live Test의 JSON 편집기와 결과 패널을 모바일에서도 읽기 쉽게 고쳐줘.
```

```text
$evaluation-hub 사이드바 페이지 표시를 더 단순한 단추형 UI로 바꾸고 다크·라이트 테마를 검증해줘.
```

## Backend and review

```text
$evaluation-hub 이 기능을 FastAPI async route, AsyncSession, httpx.AsyncClient 기반으로 구현하고 모든 Python 테스트를 uv run으로 실행해줘.
```

```text
$evaluation-hub 동기 SQLAlchemy 세션이나 event loop를 막는 호출이 남아 있는지 검사하고 async 회귀 테스트를 추가해줘.
```

```text
$evaluation-hub 외부 endpoint 호출의 SSRF, timeout, secret 노출 위험을 리뷰해줘. 수정은 하지 마.
```

```text
$evaluation-hub 현재 변경사항이 FastAPI template 기반 인증과 사용자 관리 기능을 깨뜨리지 않는지 검증해줘.
```
