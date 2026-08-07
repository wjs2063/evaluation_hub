import { createFileRoute } from "@tanstack/react-router"

import { SingleTurnWorkspace } from "@/components/Evaluations/SingleTurnWorkspace"

export const Route = createFileRoute(
  "/_layout/evaluation-single-turn/live-test",
)({
  component: LiveApiTest,
  head: () => ({ meta: [{ title: "Live API Test - EvalHub" }] }),
})

function LiveApiTest() {
  return (
    <SingleTurnWorkspace
      title="라이브 API 테스트"
      description="요청 형식과 테스트 데이터를 저장한 뒤 A 서버를 호출하고, 실제 응답을 기대값과 비교합니다."
    />
  )
}
