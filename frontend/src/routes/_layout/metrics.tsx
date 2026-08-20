import { createFileRoute } from "@tanstack/react-router"

import { PageHeader } from "@/components/Common/PageHeader"
import { MetricManagement } from "@/components/Evaluations/MetricManagement"

export const Route = createFileRoute("/_layout/metrics")({
  component: Metrics,
  head: () => ({ meta: [{ title: "Metrics - EvalHub" }] }),
})

function Metrics() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Manage"
        title="메트릭 관리"
        description="모든 인증 사용자가 평가 범위별 CustomMetric과 공유 프로필을 관리합니다."
      />
      <MetricManagement />
    </div>
  )
}
