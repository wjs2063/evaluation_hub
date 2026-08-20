import { Badge } from "@/components/ui/badge"

export type EvaluationMetric = {
  name: string
  display_name?: string | null
  score: number
  weight_percent?: number | null
  weighted_score?: number | null
  raw_score_ratio?: number | null
  score_direction?: string | null
  reason: string | null
  error?: string | null
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

const formatScore = (score: number) => `${score.toFixed(3)}점`

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
                {metric.display_name ?? metricNames[metric.name] ?? metric.name}
              </p>
              <span className="tabular-nums text-xs font-semibold">
                {formatScore(metric.score)}
              </span>
            </div>
            {metric.weight_percent != null && (
              <p className="mt-1 text-xs text-muted-foreground">
                가중치 {metric.weight_percent}%
                {metric.weighted_score != null &&
                  ` · 최종 기여 ${formatScore(metric.weighted_score)}`}
              </p>
            )}
            {metric.raw_score_ratio != null &&
              metric.score_direction === "lower_is_better" && (
                <p className="mt-1 text-xs text-muted-foreground">
                  DeepEval 원점수 {formatScore(metric.raw_score_ratio * 100)} ·
                  낮을수록 좋음 · 합산용 품질점수 {formatScore(metric.score)}
                </p>
              )}
            <p className="mt-2 whitespace-pre-wrap break-words text-muted-foreground">
              {metric.error ??
                metric.reason ??
                "평가 이유가 제공되지 않았습니다."}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
