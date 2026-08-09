import { Link as RouterLink } from "@tanstack/react-router"
import axios from "axios"
import { ChevronRight, History, Play } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { PageHeader } from "@/components/Common/PageHeader"
import {
  EvaluationDetails,
  type EvaluationMetric,
} from "@/components/Evaluations/EvaluationDetails"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

type Dataset = {
  id: string
  name: string
  description: string | null
  row_count: number
}

type RunRow = {
  id: string
  input: string
  expected_output: string
  actual_output: string
  response_status: number | null
  score: number
  passed: boolean
  metrics: EvaluationMetric[]
  error: string | null
  baseline_actual_output?: string | null
  output_changed?: boolean | null
  score_delta?: number | null
}

type Run = {
  id: string
  created_at: string
  total: number
  passed: number
  failed: number
  average_score: number
  baseline_run_id: string | null
  rows?: RunRow[]
}

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? "" })
api.interceptors.request.use((config) => {
  config.headers.Authorization = `Bearer ${localStorage.getItem("access_token") ?? ""}`
  return config
})

export function RegressionWorkspace() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetId, setDatasetId] = useState("")
  const [runs, setRuns] = useState<Run[]>([])
  const [runId, setRunId] = useState("")
  const [baselineRunId, setBaselineRunId] = useState("")
  const [selectedRun, setSelectedRun] = useState<Run | null>(null)
  const [error, setError] = useState("")
  const [isRunning, setIsRunning] = useState(false)

  const loadRuns = useCallback(async (id: string) => {
    const { data } = await api.get<{ data: Run[] }>(
      `/api/v1/evaluations/datasets/${id}/runs`,
    )
    setRuns(data.data)
    setRunId(data.data[0]?.id ?? "")
  }, [])

  useEffect(() => {
    api
      .get<{ data: Dataset[] }>("/api/v1/evaluations/datasets", {
        params: { evaluation_type: "single_turn" },
      })
      .then(({ data }) => {
        setDatasets(data.data)
        const firstId = data.data[0]?.id ?? ""
        setDatasetId(firstId)
        if (firstId) return loadRuns(firstId)
      })
      .catch(() => setError("회귀 테스트 이력을 불러오지 못했습니다."))
  }, [loadRuns])

  useEffect(() => {
    if (!datasetId || !runId) {
      setSelectedRun(null)
      return
    }
    api
      .get<Run>(`/api/v1/evaluations/datasets/${datasetId}/runs/${runId}`)
      .then(({ data }) => setSelectedRun(data))
      .catch(() => setError("실행 상세 결과를 불러오지 못했습니다."))
  }, [datasetId, runId])

  const runRegression = async () => {
    if (!datasetId) return
    try {
      setIsRunning(true)
      setError("")
      const { data } = await api.post<Run>(
        `/api/v1/evaluations/datasets/${datasetId}/run`,
        undefined,
        { params: { baseline_run_id: baselineRunId || undefined } },
      )
      await loadRuns(datasetId)
      setRunId(data.id)
    } catch (requestError) {
      const detail = axios.isAxiosError(requestError)
        ? requestError.response?.data?.detail
        : null
      setError(detail ?? "회귀 테스트 실행에 실패했습니다.")
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Single-turn"
        title="회귀 테스트"
        description="저장된 실행 결과를 다시 검토해 A 서버 응답의 품질 변화를 확인합니다."
      />
      {error && (
        <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </p>
      )}
      <section className="console-surface p-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">테스트 데이터셋</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              데이터셋과 실행 시점을 선택하면 입력·실제 응답·기대값을 나란히
              확인할 수 있습니다.
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={runRegression}
              disabled={!datasetId || isRunning}
            >
              <Play /> {isRunning ? "실행 중…" : "회귀 테스트 실행"}
            </Button>
            <Button size="sm" variant="outline" asChild>
              <RouterLink to="/evaluation-single-turn/live-test">
                실행 설정 <ChevronRight />
              </RouterLink>
            </Button>
          </div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span className="text-xs text-muted-foreground">테스트</span>
            <select
              className="h-9 w-full rounded-md border bg-transparent px-3"
              value={datasetId}
              onChange={(event) => {
                const id = event.target.value
                setDatasetId(id)
                loadRuns(id).catch(() =>
                  setError("실행 이력을 불러오지 못했습니다."),
                )
              }}
            >
              <option value="">데이터셋을 선택하세요</option>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name} ({dataset.row_count.toLocaleString()} rows)
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-xs text-muted-foreground">
              기준 실행 (선택)
            </span>
            <select
              className="h-9 w-full rounded-md border bg-transparent px-3"
              value={baselineRunId}
              onChange={(event) => setBaselineRunId(event.target.value)}
            >
              <option value="">기준 없이 기대값만 비교</option>
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {new Date(run.created_at).toLocaleString()} · 평균{" "}
                  {(run.average_score * 100).toFixed(2)}%
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-xs text-muted-foreground">실행 이력</span>
            <select
              className="h-9 w-full rounded-md border bg-transparent px-3"
              value={runId}
              onChange={(event) => setRunId(event.target.value)}
              disabled={runs.length === 0}
            >
              <option value="">실행 이력을 선택하세요</option>
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {new Date(run.created_at).toLocaleString()} · {run.passed}/
                  {run.total} 통과
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      {!selectedRun && (
        <section className="console-surface grid min-h-52 place-items-center p-8 text-center">
          <div>
            <History className="mx-auto size-7 text-muted-foreground" />
            <p className="mt-3 text-sm text-muted-foreground">
              아직 실행 이력이 없습니다. 실행 화면에서 A 서버 호출 평가를
              시작하세요.
            </p>
          </div>
        </section>
      )}
      {selectedRun && (
        <section className="console-surface overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b p-5">
            <div>
              <h2 className="text-sm font-semibold">실행 결과</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {new Date(selectedRun.created_at).toLocaleString()}
              </p>
            </div>
            <div className="flex gap-2">
              <Badge variant="secondary">
                통과 {selectedRun.passed}/{selectedRun.total}
              </Badge>
              <Badge variant="outline">
                평균 {(selectedRun.average_score * 100).toFixed(2)}%
              </Badge>
            </div>
          </div>
          <div className="divide-y">
            {selectedRun.rows?.map((row, index) => (
              <article
                key={row.id}
                className="grid gap-4 p-5 text-sm lg:grid-cols-4"
              >
                <div>
                  <p className="mb-1 text-xs text-muted-foreground">
                    {index + 1}. Input
                  </p>
                  <pre className="whitespace-pre-wrap break-words font-sans">
                    {row.input}
                  </pre>
                </div>
                {selectedRun.baseline_run_id && (
                  <div>
                    <p className="mb-1 text-xs text-muted-foreground">
                      Baseline comparison
                    </p>
                    <pre className="whitespace-pre-wrap break-words font-sans">
                      {row.baseline_actual_output ?? "기준 행 없음"}
                    </pre>
                    <Badge
                      className="mt-3"
                      variant={row.output_changed ? "destructive" : "secondary"}
                    >
                      {row.output_changed ? "응답 변경" : "변경 없음"} ·{" "}
                      {row.score_delta && row.score_delta > 0 ? "+" : ""}
                      {((row.score_delta ?? 0) * 100).toFixed(2)}p
                    </Badge>
                  </div>
                )}
                <div>
                  <p className="mb-1 text-xs text-muted-foreground">
                    Actual{" "}
                    {row.response_status ? `(${row.response_status})` : ""}
                  </p>
                  <pre className="whitespace-pre-wrap break-words font-sans">
                    {row.error ?? row.actual_output}
                  </pre>
                </div>
                <div>
                  <p className="mb-1 text-xs text-muted-foreground">Expected</p>
                  <pre className="whitespace-pre-wrap break-words font-sans">
                    {row.expected_output}
                  </pre>
                </div>
                <EvaluationDetails
                  className="lg:col-span-4"
                  score={row.score}
                  passed={row.passed}
                  metrics={row.metrics}
                />
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
