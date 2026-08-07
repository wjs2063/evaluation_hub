import { createFileRoute } from "@tanstack/react-router"

import { EvaluationComingSoon } from "@/components/Evaluations/EvaluationComingSoon"

export const Route = createFileRoute("/_layout/evaluation-rag")({
  component: RagEvaluation,
  head: () => ({ meta: [{ title: "RAG Test - EvalHub" }] }),
})

function RagEvaluation() {
  return (
    <EvaluationComingSoon
      title="RAG 테스트"
      description="검색 결과와 생성 응답의 품질을 함께 검증하는 기능입니다."
    />
  )
}
