import { Construction } from "lucide-react"

import { PageHeader } from "@/components/Common/PageHeader"
import { Badge } from "@/components/ui/badge"

interface EvaluationComingSoonProps {
  title: string
  description: string
}

export function EvaluationComingSoon({
  title,
  description,
}: EvaluationComingSoonProps) {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Evaluation workspace"
        title={title}
        description={description}
      />

      <section className="console-surface grid min-h-80 place-items-center p-8 text-center">
        <div>
          <span className="mx-auto grid size-12 place-items-center rounded-full bg-cyan-400/10 text-cyan-500">
            <Construction className="size-6" />
          </span>
          <Badge variant="secondary" className="mt-4">
            지원 예정
          </Badge>
          <h2 className="mt-3 text-lg font-semibold">준비 중인 기능입니다</h2>
          <p className="mt-2 max-w-md text-sm text-muted-foreground">
            해당 평가 기능은 현재 지원 예정입니다. 제공 준비가 완료되면 이
            페이지에서 이용할 수 있습니다.
          </p>
        </div>
      </section>
    </div>
  )
}
