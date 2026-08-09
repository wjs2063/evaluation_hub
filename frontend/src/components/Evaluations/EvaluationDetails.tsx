import { Badge } from "@/components/ui/badge"

export type EvaluationMetric = {
  name: string
  score: number
  reason: string | null
}

type EvaluationDetailsProps = {
  score: number
  passed: boolean
  metrics: EvaluationMetric[]
  className?: string
}

const metricNames: Record<string, string> = {
  exact_match: "정확 일치",
  similarity: "문자열 유사도",
  token_recall: "핵심 토큰 포함률",
  deepeval_geval: "자연어 응답 정확성",
}

const formatScore = (score: number) => `${(score * 100).toFixed(2)}%`

export function EvaluationDetails({
  score,
  passed,
  metrics,
  className = "",
}: EvaluationDetailsProps) {
  if (metrics.length === 0) return null

  return (
    <div className={`rounded-md border bg-muted/20 p-3 ${className}`}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs font-medium text-muted-foreground">종합 점수</p>
        <Badge variant={passed ? "secondary" : "destructive"}>
          {passed ? "통과" : "실패"} · {formatScore(score)}
        </Badge>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {metrics.map((metric, index) => (
          <div
            key={`${metric.name}-${index}`}
            className="rounded-md border p-3"
          >
            <div className="flex items-center justify-between gap-3">
              <p className="font-medium">
                {metricNames[metric.name] ?? metric.name}
              </p>
              <span className="tabular-nums text-xs font-semibold">
                {formatScore(metric.score)}
              </span>
            </div>
            <p className="mt-2 whitespace-pre-wrap break-words text-muted-foreground">
              {metric.reason ?? "평가 이유가 제공되지 않았습니다."}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
