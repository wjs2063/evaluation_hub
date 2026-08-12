import { createFileRoute, Link as RouterLink } from "@tanstack/react-router"
import axios from "axios"
import {
  CheckCircle2,
  CircleAlert,
  FileJson2,
  FlaskConical,
  LoaderCircle,
  UploadCloud,
} from "lucide-react"
import { type FormEvent, useState } from "react"

import { PageHeader } from "@/components/Common/PageHeader"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

type Metric = { name: string; score: number }
type EvaluationRow = {
  index: number
  input: string
  actual_output: string
  expected_output: string
  score: number
  passed: boolean
  metrics: Metric[]
}
type EvaluationResult = {
  evaluator: string
  total: number
  passed: number
  failed: number
  pass_rate: number
  average_score: number
  rows: EvaluationRow[]
}

export const Route = createFileRoute("/_layout/evaluations")({
  component: Evaluations,
  head: () => ({ meta: [{ title: "Evaluations - EvalHub" }] }),
})

const formatPercent = (value: number) => `${Math.round(value * 100)}%`
const formatScore = (value: number) => `${(value * 100).toFixed(2)}점`

function Evaluations() {
  const [file, setFile] = useState<File | null>(null)
  const [threshold, setThreshold] = useState(0.7)
  const [result, setResult] = useState<EvaluationResult | null>(null)
  const [error, setError] = useState("")
  const [isRunning, setIsRunning] = useState(false)

  const runEvaluation = async (event: FormEvent) => {
    event.preventDefault()
    if (!file || isRunning) return

    const body = new FormData()
    body.append("file", file)
    body.append("framework", "local")
    body.append("threshold", String(threshold))

    setError("")
    setIsRunning(true)
    try {
      const response = await axios.post<EvaluationResult>(
        `${import.meta.env.VITE_API_URL ?? ""}/api/v1/evaluations/run`,
        body,
        {
          headers: {
            Authorization: `Bearer ${localStorage.getItem("access_token") ?? ""}`,
          },
        },
      )
      setResult(response.data)
    } catch (requestError) {
      const fallback =
        "평가 실행에 실패했습니다. 데이터셋 형식을 확인해 주세요."
      setError(
        axios.isAxiosError(requestError)
          ? (requestError.response?.data?.detail ?? fallback)
          : fallback,
      )
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="AI quality workspace"
        title="평가 기능 안내 및 빠른 로컬 채점"
        description="저장형 라이브 API 테스트와 회귀 평가는 사이드바에서 시작하세요. 이 화면은 외부 API를 호출하지 않는 빠른 로컬 채점 도구입니다."
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(320px,0.75fr)_minmax(0,1.25fr)]">
        <form onSubmit={runEvaluation} className="console-surface h-fit">
          <div className="border-b px-5 py-4">
            <h2 className="text-sm font-semibold">빠른 로컬 채점</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              최대 5MB · UTF-8 · CSV 또는 JSON
            </p>
          </div>
          <div className="space-y-5 p-5">
            <label
              htmlFor="evaluation-dataset"
              className="grid min-h-44 cursor-pointer place-items-center rounded-md border border-dashed bg-muted/25 p-6 text-center transition-colors hover:bg-muted/50"
            >
              <span>
                <UploadCloud className="mx-auto mb-3 size-8 text-primary" />
                <span className="block text-sm font-medium">
                  {file ? file.name : "데이터셋을 선택하세요"}
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  input, actual_output, expected_output 필드가 필요합니다.
                </span>
              </span>
              <Input
                id="evaluation-dataset"
                type="file"
                accept=".csv,.json,application/json,text/csv"
                className="sr-only"
                onChange={(event) => {
                  setFile(event.target.files?.[0] ?? null)
                  setResult(null)
                  setError("")
                }}
              />
            </label>

            <div>
              <div className="mb-2 flex items-center justify-between text-sm">
                <label htmlFor="threshold" className="font-medium">
                  통과 기준
                </label>
                <span className="font-mono text-xs text-primary">
                  {formatScore(threshold)}
                </span>
              </div>
              <input
                id="threshold"
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={threshold}
                onChange={(event) => setThreshold(Number(event.target.value))}
                className="w-full accent-primary"
              />
            </div>

            <div className="rounded-md border bg-muted/20 p-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium">Local baseline</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Exact match · Similarity · Token recall
                  </p>
                </div>
                <Badge variant="secondary">Ready</Badge>
              </div>
              <div className="mt-3 flex gap-2 text-[11px] text-muted-foreground">
                <Badge variant="outline">DeepEval adapter</Badge>
                <Badge variant="outline">Langfuse adapter</Badge>
              </div>
            </div>

            {error && (
              <p className="flex items-start gap-2 rounded-md bg-destructive/10 p-3 text-xs text-destructive">
                <CircleAlert className="mt-0.5 size-4 shrink-0" />
                {error}
              </p>
            )}

            <Button
              type="submit"
              className="w-full"
              disabled={!file || isRunning}
            >
              {isRunning ? (
                <LoaderCircle className="animate-spin" />
              ) : (
                <FlaskConical />
              )}
              {isRunning ? "채점 중…" : "로컬 채점 실행"}
            </Button>
            <Button type="button" variant="outline" className="w-full" asChild>
              <RouterLink to="/evaluation-single-turn/live-test">
                저장형 라이브 API 테스트로 이동
              </RouterLink>
            </Button>
          </div>
        </form>

        <section className="console-surface min-w-0">
          <div className="flex items-center justify-between border-b px-5 py-4">
            <div>
              <h2 className="text-sm font-semibold">평가 결과</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {result ? result.evaluator : "실행 결과가 여기에 표시됩니다."}
              </p>
            </div>
            {result && <Badge variant="outline">{result.total} rows</Badge>}
          </div>

          {!result ? (
            <div className="grid min-h-[430px] place-items-center p-8 text-center">
              <div>
                <FileJson2 className="mx-auto mb-3 size-10 text-muted-foreground/35" />
                <p className="text-sm font-medium">아직 평가 결과가 없습니다</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  왼쪽에서 데이터셋을 업로드하고 평가를 실행해 주세요.
                </p>
              </div>
            </div>
          ) : (
            <div>
              <div className="grid grid-cols-2 gap-px border-b bg-border sm:grid-cols-4">
                {[
                  ["평균 점수", formatScore(result.average_score)],
                  ["통과율", formatPercent(result.pass_rate)],
                  ["통과", String(result.passed)],
                  ["실패", String(result.failed)],
                ].map(([label, value]) => (
                  <div key={label} className="bg-card p-4">
                    <p className="console-label">{label}</p>
                    <p className="mt-2 text-xl font-semibold">{value}</p>
                  </div>
                ))}
              </div>

              <div className="max-h-[520px] divide-y overflow-auto">
                {result.rows.map((row) => (
                  <article key={row.index} className="p-5">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        {row.passed ? (
                          <CheckCircle2 className="size-4 shrink-0 text-emerald-500" />
                        ) : (
                          <CircleAlert className="size-4 shrink-0 text-destructive" />
                        )}
                        <p className="truncate text-sm font-medium">
                          #{row.index + 1} {row.input}
                        </p>
                      </div>
                      <Badge variant={row.passed ? "secondary" : "destructive"}>
                        {formatScore(row.score)}
                      </Badge>
                    </div>
                    <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                      <div className="rounded-md bg-muted/35 p-3">
                        <p className="mb-1 font-medium text-muted-foreground">
                          Actual
                        </p>
                        <p>{row.actual_output}</p>
                      </div>
                      <div className="rounded-md bg-muted/35 p-3">
                        <p className="mb-1 font-medium text-muted-foreground">
                          Expected
                        </p>
                        <p>{row.expected_output}</p>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
