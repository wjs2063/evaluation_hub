import { Link as RouterLink } from "@tanstack/react-router"
import axios from "axios"
import { ChevronLeft, ChevronRight, History, Play } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { PageHeader } from "@/components/Common/PageHeader"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import useAuth from "@/hooks/useAuth"

type Endpoint = { id: string; is_active: boolean }

type Scenario = {
  id: string
  name: string
  description: string | null
  turn_count: number
}

type ScenarioRunTurn = {
  id: string
  identifier: string
  request_body: string
  actual_output: string
  expected_output: string
  response_status: number | null
  score: number
  passed: boolean
  reason: string | null
  error: string | null
  baseline_actual_output: string | null
  output_changed: boolean | null
  score_delta: number | null
}

type ScenarioRun = {
  id: string
  scenario_id: string
  baseline_run_id: string | null
  created_at: string
  total: number
  passed: number
  failed: number
  turn_average_score: number
  conversation_score: number | null
  conversation_reason: string | null
  overall_score: number
  overall_passed: boolean
  overall_reason: string | null
  average_score: number
  geval_score: number | null
  geval_reason: string | null
  error: string | null
  turns?: ScenarioRunTurn[]
}

const RUNS_PER_PAGE = 10

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? "" })
api.interceptors.request.use((config) => {
  config.headers.Authorization = `Bearer ${localStorage.getItem("access_token") ?? ""}`
  return config
})

const scorePoints = (score: number) => `${score.toFixed(3)}점`

export function MultiTurnRegressionWorkspace() {
  const { user } = useAuth()
  const [endpoints, setEndpoints] = useState<Endpoint[]>([])
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [scenarioId, setScenarioId] = useState("")
  const [runs, setRuns] = useState<ScenarioRun[]>([])
  const [runCount, setRunCount] = useState(0)
  const [runPage, setRunPage] = useState(0)
  const [runId, setRunId] = useState("")
  const [baselineRunId, setBaselineRunId] = useState("")
  const [error, setError] = useState("")
  const [isRunning, setIsRunning] = useState(false)
  const [endpointsLoaded, setEndpointsLoaded] = useState(false)
  const hasEndpoints = endpoints.some((endpoint) => endpoint.is_active)

  const [selectedRun, setSelectedRun] = useState<ScenarioRun | null>(null)

  const loadRuns = useCallback(
    async (id: string, page = 0, preferredRunId?: string) => {
      const { data } = await api.get<{ data: ScenarioRun[]; count: number }>(
        `/api/v1/evaluations/multi-turn/datasets/${id}/runs`,
        { params: { offset: page * RUNS_PER_PAGE, limit: RUNS_PER_PAGE } },
      )
      setRuns(data.data)
      setRunCount(data.count)
      setRunId(preferredRunId ?? data.data[0]?.id ?? "")
    },
    [],
  )

  useEffect(() => {
    if (!scenarioId || !runId) {
      setSelectedRun(null)
      return
    }
    api
      .get<ScenarioRun>(
        `/api/v1/evaluations/multi-turn/datasets/${scenarioId}/runs/${runId}`,
      )
      .then(({ data }) => setSelectedRun(data))
      .catch(() => setError("실행 상세 결과를 불러오지 못했습니다."))
  }, [scenarioId, runId])

  useEffect(() => {
    Promise.all([
      api.get<{ data: Scenario[] }>("/api/v1/evaluations/multi-turn/datasets"),
      api.get<{ data: Endpoint[] }>("/api/v1/evaluations/endpoints", {
        params: { limit: 200 },
      }),
    ])
      .then(([scenarioResult, endpointResult]) => {
        setScenarios(scenarioResult.data.data)
        setEndpoints(endpointResult.data.data)
        setEndpointsLoaded(true)
        const firstId = scenarioResult.data.data[0]?.id ?? ""
        setScenarioId(firstId)
        if (firstId) return loadRuns(firstId)
      })
      .catch(() => setError("멀티턴 시나리오 이력을 불러오지 못했습니다."))
  }, [loadRuns])

  const changeScenario = (id: string) => {
    setScenarioId(id)
    setBaselineRunId("")
    setRunPage(0)
    setRuns([])
    setRunId("")
    if (id) {
      loadRuns(id).catch(() => setError("실행 이력을 불러오지 못했습니다."))
    }
  }

  const runRegression = async () => {
    if (!scenarioId) return
    try {
      setIsRunning(true)
      setError("")
      const { data } = await api.post<ScenarioRun>(
        `/api/v1/evaluations/multi-turn/datasets/${scenarioId}/run`,
        undefined,
        { params: { baseline_run_id: baselineRunId || undefined } },
      )
      setRunPage(0)
      await loadRuns(scenarioId, 0, data.id)
    } catch (requestError) {
      const detail = axios.isAxiosError(requestError)
        ? requestError.response?.data?.detail
        : null
      setError(detail ?? "멀티턴 회귀 테스트 실행에 실패했습니다.")
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Multi-turn"
        title="회귀 테스트"
        description="기준 실행과 최신 대화를 비교해 turn별 자연어 응답과 점수 변화를 확인합니다."
      />
      {error && (
        <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </p>
      )}
      {endpointsLoaded && !hasEndpoints && (
        <section className="console-surface border-amber-500/30 bg-amber-500/10 p-4 text-sm">
          <p className="font-medium">
            등록된 활성 A 서버가 없어 회귀 테스트를 실행할 수 없습니다.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {user?.is_superuser
              ? "A 서버를 등록한 뒤 이 화면을 새로고침하세요."
              : "관리자에게 A 서버 등록을 요청해 주세요."}
          </p>
          {user?.is_superuser && (
            <RouterLink
              className="mt-3 inline-block text-sm text-primary underline"
              to="/admin"
            >
              A 서버 관리로 이동
            </RouterLink>
          )}
        </section>
      )}
      <section className="console-surface p-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">시나리오와 기준 실행</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              기준 실행을 고르면 새 실행의 turn별 실제 응답과 점수 차이를 함께
              저장합니다.
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={runRegression}
              disabled={!scenarioId || isRunning || !hasEndpoints}
            >
              <Play /> {isRunning ? "실행 중…" : "회귀 테스트 실행"}
            </Button>
            <Button size="sm" variant="outline" asChild>
              <RouterLink to="/evaluation-multi-turn/live-test">
                실행 설정 <ChevronRight />
              </RouterLink>
            </Button>
          </div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <label className="space-y-1 text-sm">
            <span className="text-xs text-muted-foreground">시나리오</span>
            <select
              className="h-9 w-full rounded-md border bg-transparent px-3"
              value={scenarioId}
              onChange={(event) => changeScenario(event.target.value)}
            >
              <option value="">시나리오를 선택하세요</option>
              {scenarios.map((scenario) => (
                <option key={scenario.id} value={scenario.id}>
                  {scenario.name} ({scenario.turn_count} turns)
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
                  {new Date(run.created_at).toLocaleString()} · 종합{" "}
                  {scorePoints(run.overall_score)}
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
              아직 실행 이력이 없습니다. 라이브 테스트에서 시나리오를 만들고
              실행하세요.
            </p>
          </div>
        </section>
      )}
      {selectedRun && (
        <section className="console-surface overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b p-5">
            <div>
              <h2 className="text-sm font-semibold">대화 실행 결과</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                {new Date(selectedRun.created_at).toLocaleString()}
                {selectedRun.baseline_run_id ? " · 기준 실행 비교" : ""}
              </p>
            </div>
            <div className="flex gap-2">
              <Badge
                variant={
                  selectedRun.overall_passed ? "secondary" : "destructive"
                }
              >
                최종 {selectedRun.overall_passed ? "통과" : "실패"}
              </Badge>
              <Badge variant="outline">
                종합 {scorePoints(selectedRun.overall_score)}
              </Badge>
              <Badge variant="outline">
                턴 평균 {scorePoints(selectedRun.turn_average_score)}
              </Badge>
              {selectedRun.conversation_score !== null && (
                <Badge variant="outline">
                  대화 흐름 {scorePoints(selectedRun.conversation_score)}
                </Badge>
              )}
            </div>
          </div>
          {selectedRun.overall_reason && (
            <p className="border-b bg-muted/30 p-4 text-sm">
              {selectedRun.overall_reason}
            </p>
          )}
          {selectedRun.error && (
            <p className="border-b bg-destructive/10 p-4 text-xs text-destructive">
              {selectedRun.error}
            </p>
          )}
          <div className="divide-y">
            {selectedRun.turns?.map((turn) => (
              <article
                key={turn.id}
                className={`grid gap-4 p-5 text-sm ${selectedRun.baseline_run_id ? "xl:grid-cols-4" : "xl:grid-cols-3"}`}
              >
                <div>
                  <p className="mb-1 text-xs text-muted-foreground">
                    {turn.identifier} · 요청
                  </p>
                  <pre className="whitespace-pre-wrap break-words font-sans">
                    {turn.request_body}
                  </pre>
                </div>
                {selectedRun.baseline_run_id && (
                  <div>
                    <p className="mb-1 text-xs text-muted-foreground">
                      기준 실행 응답
                    </p>
                    <pre className="whitespace-pre-wrap break-words font-sans">
                      {turn.baseline_actual_output ?? "기준 turn 없음"}
                    </pre>
                    <Badge
                      className="mt-3"
                      variant={
                        turn.output_changed ? "destructive" : "secondary"
                      }
                    >
                      {turn.output_changed ? "응답 변경" : "변경 없음"} ·{" "}
                      {(turn.score_delta ?? 0) > 0 ? "+" : ""}
                      {(turn.score_delta ?? 0).toFixed(3)}점
                    </Badge>
                  </div>
                )}
                <div>
                  <p className="mb-1 text-xs text-muted-foreground">
                    실제 응답{" "}
                    {turn.response_status ? `(${turn.response_status})` : ""}
                  </p>
                  <pre className="whitespace-pre-wrap break-words font-sans">
                    {turn.error ?? turn.actual_output}
                  </pre>
                </div>
                <div>
                  <p className="mb-1 text-xs text-muted-foreground">
                    기대 응답
                  </p>
                  <pre className="whitespace-pre-wrap break-words font-sans">
                    {turn.expected_output}
                  </pre>
                  <Badge
                    className="mt-3"
                    variant={turn.passed ? "secondary" : "destructive"}
                  >
                    {scorePoints(turn.score)}
                  </Badge>
                  {turn.reason && (
                    <p className="mt-2 text-xs text-muted-foreground">
                      {turn.reason}
                    </p>
                  )}
                </div>
              </article>
            ))}
          </div>
          {runCount > RUNS_PER_PAGE && (
            <div className="flex items-center justify-between border-t p-4 text-xs text-muted-foreground">
              <span>
                총 {runCount.toLocaleString()}건 · {runPage + 1}/
                {Math.ceil(runCount / RUNS_PER_PAGE)} 페이지
              </span>
              <div className="flex gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={runPage === 0}
                  onClick={() => {
                    const next = Math.max(0, runPage - 1)
                    setRunPage(next)
                    void loadRuns(scenarioId, next)
                  }}
                >
                  <ChevronLeft /> 이전
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={(runPage + 1) * RUNS_PER_PAGE >= runCount}
                  onClick={() => {
                    const next = runPage + 1
                    setRunPage(next)
                    void loadRuns(scenarioId, next)
                  }}
                >
                  다음 <ChevronRight />
                </Button>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
