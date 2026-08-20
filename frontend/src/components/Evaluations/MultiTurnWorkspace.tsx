import { Link as RouterLink } from "@tanstack/react-router"
import axios from "axios"
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Play,
  Plus,
  Save,
  Trash2,
  Upload,
} from "lucide-react"
import { type ChangeEvent, useCallback, useEffect, useState } from "react"

import { PageHeader } from "@/components/Common/PageHeader"
import { ComparisonPanel } from "@/components/Evaluations/ComparisonPanel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import useAuth from "@/hooks/useAuth"

type Endpoint = {
  id: string
  name: string
  base_url: string
  is_active: boolean
}
type MetricProfile = { id: string; name: string }
type Scenario = {
  id: string
  name: string
  description: string | null
  endpoint_id: string
  threshold: number
  evaluator: "deepeval" | "local"
  turn_count: number
  turns?: Turn[]
  created_by_id: string | null
  updated_by_id: string | null
  created_at: string
  updated_at: string
}
type Turn = {
  id?: string
  identifier: string
  url: string
  body_template: string
  response_path: string | null
  expected_output: string
  headers?: Record<string, string>
  headers_configured?: boolean
}
type TurnDraft = Pick<
  Turn,
  "url" | "body_template" | "response_path" | "expected_output"
> & {
  headers_json: string
}
type ScenarioDraft = {
  name: string
  description: string
  endpoint_id: string
  threshold: number
  evaluator: "deepeval" | "local"
  turns: TurnDraft[]
}
type ScenarioRun = {
  id: string
  created_at: string
  total: number
  passed: number
  turn_average_score: number
  conversation_score: number | null
  conversation_reason: string | null
  overall_score: number
  overall_passed: boolean
  overall_reason: string | null
  average_score: number
  evaluator: string
  geval_score: number | null
  geval_reason: string | null
  error: string | null
  turns?: {
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
  }[]
}

const RUNS_PER_PAGE = 10

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? "" })
api.interceptors.request.use((config) => {
  config.headers.Authorization = `Bearer ${localStorage.getItem("access_token") ?? ""}`
  return config
})

const initialScenario = (endpointId = "", url = "") => ({
  name: "새 멀티턴 시나리오",
  description: "",
  endpoint_id: endpointId,
  threshold: 70,
  evaluator: "deepeval",
  turns: [
    {
      identifier: "first_answer",
      url,
      headers: {},
      body_template: '{"message":"첫 질문"}',
      response_path: "/answer",
      expected_output: "기대하는 첫 응답",
    },
    {
      identifier: "follow_up",
      url,
      headers: {},
      body_template: '{"message":"첫 답변의 내용을 유지하면서 이어서 답해줘"}',
      response_path: "/answer",
      expected_output: "기대하는 후속 응답",
    },
  ],
})

const sampleDocument = (endpointId = "", url = "") => ({
  name: "상담 맥락 유지 테스트",
  description: "이전 답변의 정보를 후속 turn에서 유지하는지 평가합니다.",
  test_type: "multi_turn",
  endpoint_id: endpointId || "00000000-0000-0000-0000-000000000000",
  threshold: 70,
  evaluator: "deepeval",
  cases: [
    {
      identifier: "first_answer",
      request: {
        url: url || "https://api.example.com/v1/respond",
        headers: { "Content-Type": "application/json" },
        body: { message: "첫 질문", history: [] },
        actual_output_json_pointer: "/answer",
      },
      expected_output: "기대하는 첫 응답",
    },
    {
      identifier: "follow_up",
      request: {
        url: url || "https://api.example.com/v1/respond",
        headers: { "Content-Type": "application/json" },
        body: {
          message: "첫 답변의 내용을 유지하면서 이어서 답해줘",
          history: "{{conversation_history}}",
        },
        actual_output_json_pointer: null,
      },
      expected_output: "기대하는 후속 응답",
    },
  ],
})

const newTurn = (url = ""): TurnDraft => ({
  url,
  headers_json: "{}",
  body_template: '{"message":""}',
  response_path: "/answer",
  expected_output: "",
})

const initialDraft = (endpointId = "", url = ""): ScenarioDraft => ({
  name: "새 멀티턴 시나리오",
  description: "",
  endpoint_id: endpointId,
  threshold: 70,
  evaluator: "deepeval",
  turns: [newTurn(url)],
})

export function MultiTurnWorkspace() {
  const { user } = useAuth()
  const [endpoints, setEndpoints] = useState<Endpoint[]>([])
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [metricProfiles, setMetricProfiles] = useState<MetricProfile[]>([])
  const [runMetricProfileId, setRunMetricProfileId] = useState("")
  const [selectedId, setSelectedId] = useState("")
  const [source, setSource] = useState(
    JSON.stringify(initialScenario(), null, 2),
  )
  const [runs, setRuns] = useState<ScenarioRun[]>([])
  const [runCount, setRunCount] = useState(0)
  const [runPage, setRunPage] = useState(0)
  const [error, setError] = useState("")
  const [profileLoadError, setProfileLoadError] = useState("")
  const [busy, setBusy] = useState(false)
  const [endpointsLoaded, setEndpointsLoaded] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [draft, setDraft] = useState<ScenarioDraft>(initialDraft())
  const [draftError, setDraftError] = useState("")
  const hasEndpoints = endpoints.length > 0

  const load = useCallback(async (initializeSource = false) => {
    const [endpointResult, scenarioResult] = await Promise.all([
      api.get<{ data: Endpoint[] }>("/api/v1/evaluations/endpoints", {
        params: { limit: 200 },
      }),
      api.get<{ data: Scenario[] }>("/api/v1/evaluations/multi-turn/datasets"),
    ])
    const activeEndpoints = endpointResult.data.data.filter(
      (endpoint) => endpoint.is_active,
    )
    setEndpoints(activeEndpoints)
    setEndpointsLoaded(true)
    setScenarios(scenarioResult.data.data)
    if (initializeSource && activeEndpoints[0]) {
      setSource(
        JSON.stringify(
          initialScenario(activeEndpoints[0].id, activeEndpoints[0].base_url),
          null,
          2,
        ),
      )
    }
  }, [])

  const loadMetricProfiles = useCallback(async () => {
    setProfileLoadError("")
    try {
      const { data } = await api.get<{ data: MetricProfile[] }>(
        "/api/v1/evaluations/metric-profiles",
        { params: { evaluation_scope: "multi_turn", limit: 200 } },
      )
      const active = data.data.filter(
        (profile: MetricProfile & { is_active?: boolean }) =>
          profile.is_active !== false,
      )
      setMetricProfiles(active)
      setRunMetricProfileId((value) => value || active[0]?.id || "")
    } catch {
      setProfileLoadError("멀티턴 프로필을 불러오지 못했습니다.")
    }
  }, [])

  const loadRuns = useCallback(async (id: string, page = 0) => {
    const { data } = await api.get<{ data: ScenarioRun[]; count: number }>(
      `/api/v1/evaluations/multi-turn/datasets/${id}/runs`,
      { params: { offset: page * RUNS_PER_PAGE, limit: RUNS_PER_PAGE } },
    )
    setRuns(data.data)
    setRunCount(data.count)
  }, [])

  const loadScenario = async (id: string) => {
    const { data } = await api.get<Scenario>(
      `/api/v1/evaluations/multi-turn/datasets/${id}`,
    )
    // Header values are intentionally not returned. Explicit empty objects keep
    // the JSON format editable without exposing stored credentials.
    setSource(
      JSON.stringify(
        {
          ...data,
          turns: data.turns?.map(
            ({ id: _id, headers_configured: _configured, ...turn }) => ({
              ...turn,
              headers: {},
            }),
          ),
        },
        null,
        2,
      ),
    )
    setSelectedId(id)
    setRunPage(0)
    await loadRuns(id, 0)
  }

  const loadRunDetail = async (runId: string) => {
    if (!selectedId) return
    try {
      const { data } = await api.get<ScenarioRun>(
        `/api/v1/evaluations/multi-turn/datasets/${selectedId}/runs/${runId}`,
      )
      setRuns((current) =>
        current.map((run) => (run.id === runId ? data : run)),
      )
    } catch {
      setError("멀티턴 실행 상세 결과를 불러오지 못했습니다.")
    }
  }

  useEffect(() => {
    if (selectedId) {
      loadRuns(selectedId, runPage).catch(() =>
        setError("멀티턴 실행 이력을 불러오지 못했습니다."),
      )
    }
  }, [loadRuns, runPage, selectedId])

  useEffect(() => {
    load(true).catch(() => setError("멀티턴 시나리오를 불러오지 못했습니다."))
    void loadMetricProfiles()
  }, [load, loadMetricProfiles])

  const validateScenario = (scenario: unknown): string | null => {
    if (!scenario || typeof scenario !== "object")
      return "시나리오 JSON은 객체여야 합니다."
    const value = scenario as { endpoint_id?: unknown; turns?: unknown }
    if (typeof value.endpoint_id !== "string" || !value.endpoint_id.trim()) {
      return "관리자가 허용한 A 서버를 선택해 endpoint_id를 입력해 주세요."
    }
    const endpoint = endpoints.find((item) => item.id === value.endpoint_id)
    if (!endpoint) return "선택한 A 서버를 찾을 수 없거나 비활성화되었습니다."
    if (!Array.isArray(value.turns) || value.turns.length === 0) {
      return "시나리오에는 최소 한 개의 turn이 필요합니다."
    }
    for (let index = 0; index < value.turns.length; index += 1) {
      const turn = value.turns[index]
      if (
        !turn ||
        typeof turn !== "object" ||
        typeof (turn as { url?: unknown }).url !== "string" ||
        !(turn as { url: string }).url.trim()
      ) {
        return `${index + 1}번째 turn의 URL을 입력해 주세요.`
      }
      try {
        const url = new URL((turn as { url: string }).url)
        const baseUrl = new URL(endpoint.base_url)
        if (
          !["http:", "https:"].includes(url.protocol) ||
          url.protocol !== baseUrl.protocol ||
          url.hostname !== baseUrl.hostname ||
          url.port !== baseUrl.port
        ) {
          return `${index + 1}번째 turn URL은 선택한 A 서버와 동일한 HTTP(S) 호스트를 사용해야 합니다.`
        }
      } catch {
        return `${index + 1}번째 turn URL은 올바른 HTTP(S) URL이어야 합니다.`
      }
      try {
        const body = JSON.parse(
          String((turn as { body_template?: unknown }).body_template ?? ""),
        )
        if (!body || typeof body !== "object" || Array.isArray(body)) {
          return `${index + 1}번째 turn의 요청 body는 JSON 객체여야 합니다.`
        }
      } catch {
        return `${index + 1}번째 turn의 요청 body JSON 문법을 확인해 주세요.`
      }
    }
    return null
  }

  const save = async () => {
    try {
      setError("")
      const scenario = JSON.parse(source)
      const validationError = validateScenario(scenario)
      if (validationError) {
        setError(validationError)
        return
      }
      setBusy(true)
      const response = selectedId
        ? await api.put<Scenario>(
            `/api/v1/evaluations/multi-turn/datasets/${selectedId}`,
            scenario,
          )
        : await api.post<Scenario>(
            "/api/v1/evaluations/multi-turn/datasets",
            scenario,
          )
      await load()
      await loadScenario(response.data.id)
    } catch (requestError) {
      setError(
        axios.isAxiosError(requestError)
          ? typeof requestError.response?.data?.detail === "string"
            ? requestError.response.data.detail
            : "시나리오 저장에 실패했습니다."
          : "시나리오 JSON 형식을 확인해 주세요.",
      )
    } finally {
      setBusy(false)
    }
  }

  const openCreateForm = () => {
    const endpoint = endpoints[0]
    setDraft(initialDraft(endpoint?.id, endpoint?.base_url))
    setDraftError("")
    setCreateOpen(true)
  }

  const updateDraftTurn = <Key extends keyof TurnDraft>(
    index: number,
    key: Key,
    value: TurnDraft[Key],
  ) => {
    setDraft((current) => ({
      ...current,
      turns: current.turns.map((turn, turnIndex) =>
        turnIndex === index ? { ...turn, [key]: value } : turn,
      ),
    }))
  }

  const selectDraftEndpoint = (endpointId: string) => {
    const endpoint = endpoints.find((item) => item.id === endpointId)
    setDraft((current) => ({
      ...current,
      endpoint_id: endpointId,
      turns: current.turns.map((turn) => ({
        ...turn,
        url: endpoint?.base_url ?? "",
      })),
    }))
  }

  const createFromForm = async () => {
    if (!draft.description.trim()) {
      setDraftError("시나리오 설명을 입력해 주세요.")
      return
    }
    let turns: Turn[]
    try {
      turns = draft.turns.map((turn, index) => {
        const headers: unknown = JSON.parse(turn.headers_json)
        if (
          !headers ||
          typeof headers !== "object" ||
          Array.isArray(headers) ||
          Object.values(headers).some((value) => typeof value !== "string")
        ) {
          throw new Error(`${index + 1}번째 turn의 headers`)
        }
        const body: unknown = JSON.parse(turn.body_template)
        if (!body || typeof body !== "object" || Array.isArray(body)) {
          throw new Error(`${index + 1}번째 turn의 요청 body`)
        }
        return {
          identifier: `turn_${index + 1}`,
          url: turn.url,
          headers: headers as Record<string, string>,
          body_template: turn.body_template,
          response_path: turn.response_path,
          expected_output: turn.expected_output,
        }
      })
    } catch (headersError) {
      setDraftError(
        `${headersError instanceof Error ? headersError.message : "Turn 설정"}를 올바른 JSON 객체로 입력해 주세요. Headers의 값은 모두 문자열이어야 합니다.`,
      )
      return
    }
    const scenario = {
      ...draft,
      description: draft.description.trim(),
      turns,
    }
    const validationError = validateScenario(scenario)
    if (validationError) {
      setDraftError(validationError)
      return
    }
    try {
      setBusy(true)
      setDraftError("")
      setError("")
      const { data } = await api.post<Scenario>(
        "/api/v1/evaluations/multi-turn/datasets",
        scenario,
      )
      setCreateOpen(false)
      await load()
      await loadScenario(data.id)
    } catch (requestError) {
      setDraftError(
        axios.isAxiosError(requestError) &&
          typeof requestError.response?.data?.detail === "string"
          ? requestError.response.data.detail
          : "시나리오 생성에 실패했습니다.",
      )
    } finally {
      setBusy(false)
    }
  }

  const run = async () => {
    if (!selectedId) return setError("먼저 시나리오를 저장해 주세요.")
    if (!runMetricProfileId)
      return setError("멀티턴 메트릭 프로필을 선택해 주세요.")
    try {
      setBusy(true)
      const { data } = await api.post<ScenarioRun>(
        `/api/v1/evaluations/multi-turn/datasets/${selectedId}/run`,
        null,
        { params: { metric_profile_id: runMetricProfileId } },
      )
      setRunPage(0)
      await loadRuns(selectedId, 0)
      setRuns((current) =>
        current.map((item) => (item.id === data.id ? data : item)),
      )
    } catch (requestError) {
      setError(
        axios.isAxiosError(requestError)
          ? (requestError.response?.data?.detail ??
              "시나리오 실행에 실패했습니다.")
          : "시나리오 실행에 실패했습니다.",
      )
    } finally {
      setBusy(false)
    }
  }

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ""
    if (!file) return
    try {
      const body = new FormData()
      body.append("file", file)
      const { data } = await api.post<Scenario>(
        "/api/v1/evaluations/multi-turn/datasets/import",
        body,
      )
      await load()
      await loadScenario(data.id)
    } catch (uploadError) {
      const detail = axios.isAxiosError(uploadError)
        ? uploadError.response?.data?.detail
        : null
      setError(detail ?? "멀티턴 테스트셋 JSON 형식을 확인해 주세요.")
    }
  }

  const downloadSample = () => {
    const endpoint = endpoints[0]
    const sample = sampleDocument(endpoint?.id, endpoint?.base_url)
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(sample, null, 2)], {
        type: "application/json",
      }),
    )
    const link = document.createElement("a")
    link.href = url
    link.download = "multi-turn-dataset-sample.json"
    link.click()
    URL.revokeObjectURL(url)
  }

  const downloadDataset = async () => {
    if (!selectedId) return
    try {
      const { data } = await api.get<Blob>(
        `/api/v1/evaluations/multi-turn/datasets/${selectedId}/export`,
        { responseType: "blob" },
      )
      const url = URL.createObjectURL(data)
      const link = document.createElement("a")
      link.href = url
      link.download = `multi-turn-dataset-${selectedId}.json`
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      setError("등록된 멀티턴 테스트셋 JSON을 다운로드하지 못했습니다.")
    }
  }

  const downloadRunReport = async (runId: string) => {
    if (!selectedId) return
    try {
      const { data } = await api.get<Blob>(
        `/api/v1/evaluations/multi-turn/datasets/${selectedId}/runs/${runId}/report.html`,
        { responseType: "blob" },
      )
      const url = URL.createObjectURL(data)
      const link = document.createElement("a")
      link.href = url
      link.download = `multi-turn-report-${runId}.html`
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      setError("멀티턴 HTML 결과지를 다운로드하지 못했습니다.")
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Evaluation workspace"
        title="멀티턴 라이브 API 테스트"
        description="각 turn의 URL·JSON 본문·응답 경로를 선언하고, POST 요청으로 이전 응답을 다음 요청에 안전하게 연결합니다."
      />
      <ComparisonPanel evaluationMode="multi_turn" targetId={selectedId} />
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>멀티턴 시나리오 추가</DialogTitle>
            <DialogDescription>
              A 서버와 각 turn의 요청·기대 응답을 입력해 웹에서 바로 시나리오를
              만듭니다.
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-5"
            onSubmit={(event) => {
              event.preventDefault()
              createFromForm()
            }}
          >
            <div className="grid gap-3 md:grid-cols-2">
              <label htmlFor="scenario-name" className="space-y-1 text-sm">
                <span>시나리오 이름</span>
                <Input
                  id="scenario-name"
                  required
                  value={draft.name}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      name: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="space-y-1 text-sm">
                <span>허용된 A 서버</span>
                <select
                  className="h-9 w-full rounded-md border bg-transparent px-3 text-sm"
                  value={draft.endpoint_id}
                  onChange={(event) => selectDraftEndpoint(event.target.value)}
                >
                  <option value="">A 서버를 선택하세요</option>
                  {endpoints.map((endpoint) => (
                    <option key={endpoint.id} value={endpoint.id}>
                      {endpoint.name} · {endpoint.base_url}
                    </option>
                  ))}
                </select>
              </label>
              <label
                htmlFor="scenario-description"
                className="space-y-1 text-sm md:col-span-2"
              >
                <span>시나리오 설명</span>
                <Input
                  id="scenario-description"
                  required
                  value={draft.description}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      description: event.target.value,
                    }))
                  }
                />
              </label>
              <label htmlFor="scenario-threshold" className="space-y-1 text-sm">
                <span>평가 기준 점수 (0~100)</span>
                <Input
                  id="scenario-threshold"
                  type="number"
                  min="0"
                  max="100"
                  step="0.001"
                  value={draft.threshold}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      threshold: Number(event.target.value),
                    }))
                  }
                />
              </label>
              <label className="space-y-1 text-sm">
                <span>평가 방식</span>
                <select
                  className="h-9 w-full rounded-md border bg-transparent px-3 text-sm"
                  value={draft.evaluator}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      evaluator: event.target
                        .value as ScenarioDraft["evaluator"],
                    }))
                  }
                >
                  <option value="deepeval">DeepEval · 대화 품질</option>
                  <option value="local">Local · 빠른 비교</option>
                </select>
              </label>
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold">대화 turn</h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    각 요청은 POST JSON으로 전송되며 실행별 thread_id가 자동으로
                    추가됩니다. 별도의 history가 필요한 API는{" "}
                    <code>{"{{conversation_history}}"}</code>로 이전 질문·응답
                    전체를 전달할 수 있습니다.
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setDraft((current) => ({
                      ...current,
                      turns: [
                        ...current.turns,
                        newTurn(
                          endpoints.find(
                            (endpoint) => endpoint.id === current.endpoint_id,
                          )?.base_url,
                        ),
                      ],
                    }))
                  }
                >
                  <Plus /> Turn 추가
                </Button>
              </div>
              {draft.turns.map((turn, index) => (
                <fieldset
                  key={index}
                  className="space-y-3 rounded-md border p-4"
                >
                  <legend className="px-1 text-sm font-medium">
                    Turn {index + 1}
                  </legend>
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="self-end text-destructive hover:text-destructive"
                      disabled={draft.turns.length === 1}
                      onClick={() =>
                        setDraft((current) => ({
                          ...current,
                          turns: current.turns.filter(
                            (_, turnIndex) => turnIndex !== index,
                          ),
                        }))
                      }
                    >
                      <Trash2 /> 삭제
                    </Button>
                  </div>
                  <label
                    htmlFor={`turn-${index}-url`}
                    className="block space-y-1 text-sm"
                  >
                    <span>요청 URL</span>
                    <Input
                      id={`turn-${index}-url`}
                      required
                      type="url"
                      value={turn.url}
                      placeholder="https://api.example.com/v1/respond"
                      onChange={(event) =>
                        updateDraftTurn(index, "url", event.target.value)
                      }
                    />
                  </label>
                  <div className="grid gap-3 md:grid-cols-2">
                    <label className="space-y-1 text-sm md:col-span-2">
                      <span>요청 Headers JSON</span>
                      <textarea
                        className="min-h-20 w-full rounded-md border bg-transparent p-3 font-mono text-xs"
                        value={turn.headers_json}
                        placeholder='{"Authorization":"Bearer ..."}'
                        onChange={(event) =>
                          updateDraftTurn(
                            index,
                            "headers_json",
                            event.target.value,
                          )
                        }
                      />
                      <span className="block text-xs text-muted-foreground">
                        문자열 key/value를 가진 JSON 객체입니다. 민감한 header는
                        관리자만 저장할 수 있습니다.
                      </span>
                    </label>
                    <label className="space-y-1 text-sm">
                      <span>요청 Body JSON</span>
                      <textarea
                        className="min-h-28 w-full rounded-md border bg-transparent p-3 font-mono text-xs"
                        value={turn.body_template}
                        onChange={(event) =>
                          updateDraftTurn(
                            index,
                            "body_template",
                            event.target.value,
                          )
                        }
                      />
                    </label>
                    <div className="space-y-3">
                      <label
                        htmlFor={`turn-${index}-response-path`}
                        className="block space-y-1 text-sm"
                      >
                        <span>Actual output JSON Pointer (선택)</span>
                        <Input
                          id={`turn-${index}-response-path`}
                          value={turn.response_path ?? ""}
                          placeholder="/data/answer · 비우면 응답 전체"
                          onChange={(event) =>
                            updateDraftTurn(
                              index,
                              "response_path",
                              event.target.value || null,
                            )
                          }
                        />
                      </label>
                      <label className="block space-y-1 text-sm">
                        <span>기대 답변 / 평가 기준</span>
                        <textarea
                          className="min-h-16 w-full rounded-md border bg-transparent p-3 text-sm"
                          value={turn.expected_output}
                          placeholder="응답에 나와야 하는 내용이나 기대 답변"
                          onChange={(event) =>
                            updateDraftTurn(
                              index,
                              "expected_output",
                              event.target.value,
                            )
                          }
                        />
                      </label>
                    </div>
                  </div>
                </fieldset>
              ))}
            </div>
            {draftError && (
              <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {draftError}
              </p>
            )}
            <DialogFooter>
              <Button type="submit" disabled={busy || !hasEndpoints}>
                <Save /> {busy ? "생성 중…" : "시나리오 생성"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      {error && (
        <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="grid gap-4 xl:grid-cols-[250px_minmax(0,1fr)]">
        <aside className="console-surface h-fit p-3">
          <Button
            className="mb-3 w-full"
            size="sm"
            disabled={!hasEndpoints}
            onClick={openCreateForm}
          >
            <Plus /> 새 시나리오
          </Button>
          {scenarios.map((scenario) => (
            <button
              key={scenario.id}
              type="button"
              onClick={() =>
                loadScenario(scenario.id).catch(() =>
                  setError("시나리오를 불러오지 못했습니다."),
                )
              }
              className={`w-full rounded-md px-3 py-2 text-left text-sm ${scenario.id === selectedId ? "bg-primary/10 text-primary" : "hover:bg-muted"}`}
            >
              <p className="truncate font-medium">{scenario.name}</p>
              <p className="text-xs text-muted-foreground">
                {scenario.turn_count} turns
              </p>
            </button>
          ))}
        </aside>
        <div className="space-y-4">
          <section className="console-surface p-5">
            {endpointsLoaded && !hasEndpoints && (
              <div className="mb-4 rounded-md border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
                <p className="font-medium">
                  등록된 활성 A 서버가 없어 시나리오를 생성할 수 없습니다.
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
              </div>
            )}
            <div className="mb-3 flex flex-wrap justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold">시나리오 JSON</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  모든 turn은 JSON 본문을 가진 <code>POST</code> 요청입니다.{" "}
                  실행별 <code>thread_id</code>는 자동 추가됩니다.{" "}
                  <code>{"{{conversation_history}}"}</code>는 이전
                  user/assistant 대화 배열, <code>{"{{previous_output}}"}</code>
                  은 직전 응답입니다. DeepEval은 선택한 멀티턴 프로필의 네 지표
                  가중합으로 판정합니다. 업로드 파일은{" "}
                  <code>test_type: "multi_turn"</code>과 각 case의 request
                  headers/body, expected_output을 포함해야 합니다.
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!hasEndpoints}
                  onClick={downloadSample}
                >
                  <Download /> JSON 샘플
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!selectedId}
                  onClick={downloadDataset}
                >
                  <Download /> 테스트셋 JSON
                </Button>
                <Button variant="outline" size="sm" disabled={!hasEndpoints}>
                  <label className="cursor-pointer">
                    <Upload /> JSON 업로드
                    <input
                      type="file"
                      className="sr-only"
                      accept="application/json,.json"
                      disabled={!hasEndpoints}
                      onChange={upload}
                    />
                  </label>
                </Button>
                <Button
                  size="sm"
                  onClick={save}
                  disabled={busy || !hasEndpoints}
                >
                  <Save /> {selectedId ? "시나리오 저장" : "시나리오 생성"}
                </Button>
              </div>
            </div>
            <textarea
              aria-label="Multi-turn scenario JSON"
              className="min-h-[420px] w-full rounded-md border bg-transparent p-3 font-mono text-xs"
              value={source}
              onChange={(event) => setSource(event.target.value)}
            />
          </section>
          <section className="console-surface p-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold">실행 이력</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  한 turn이 실패하면 이후 호출은 중단되고 실패 원인이
                  보관됩니다.
                </p>
              </div>
              <div className="flex items-end gap-2">
                <label className="space-y-1 text-xs">
                  <span>멀티턴 메트릭 프로필</span>
                  <select
                    className="block h-9 rounded-md border bg-background px-2"
                    value={runMetricProfileId}
                    onChange={(event) =>
                      setRunMetricProfileId(event.target.value)
                    }
                  >
                    <option value="">선택</option>
                    {metricProfiles.map((profile) => (
                      <option key={profile.id} value={profile.id}>
                        {profile.name}
                      </option>
                    ))}
                  </select>
                  {profileLoadError ? (
                    <span className="mt-1 flex items-center gap-2 text-destructive">
                      {profileLoadError}
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => void loadMetricProfiles()}
                      >
                        다시 시도
                      </Button>
                    </span>
                  ) : metricProfiles.length === 0 ? (
                    <span className="mt-1 block text-muted-foreground">
                      활성 멀티턴 프로필이 없습니다.
                    </span>
                  ) : null}
                </label>
                <Button
                  onClick={run}
                  disabled={
                    !selectedId || busy || !hasEndpoints || !runMetricProfileId
                  }
                >
                  <Play /> {busy ? "실행 중…" : "시나리오 실행"}
                </Button>
              </div>
            </div>
            <div className="mt-4 space-y-3">
              {runs.map((run) => (
                <article
                  key={run.id}
                  className="overflow-hidden rounded-md border"
                >
                  <button
                    type="button"
                    className="flex w-full flex-wrap items-center justify-between gap-2 border-b p-3 text-left text-sm hover:bg-muted/40"
                    onClick={() => {
                      if (!run.turns) void loadRunDetail(run.id)
                    }}
                  >
                    <span>{new Date(run.created_at).toLocaleString()}</span>
                    <span className="flex flex-wrap gap-2">
                      <Badge
                        variant={
                          run.overall_passed ? "secondary" : "destructive"
                        }
                      >
                        최종 {run.overall_passed ? "통과" : "실패"}
                      </Badge>
                      <Badge variant="outline">
                        종합 {run.overall_score.toFixed(3)}점
                      </Badge>
                      <Badge variant="outline">
                        턴 평균 {run.turn_average_score.toFixed(3)}점
                      </Badge>
                      {run.conversation_score !== null && (
                        <Badge variant="outline">
                          대화 흐름 {run.conversation_score.toFixed(3)}점
                        </Badge>
                      )}
                    </span>
                  </button>
                  <div className="flex justify-end border-b px-3 py-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void downloadRunReport(run.id)}
                    >
                      <Download /> HTML 결과지
                    </Button>
                  </div>
                  {!run.turns && (
                    <p className="p-3 text-xs text-muted-foreground">
                      클릭하여 턴별 요청·응답과 평가 사유를 확인하세요.
                    </p>
                  )}
                  {run.overall_reason && (
                    <p className="border-b bg-muted/30 p-3 text-sm">
                      {run.overall_reason}
                    </p>
                  )}
                  {run.error && (
                    <p className="border-b bg-destructive/10 p-3 text-xs text-destructive">
                      {run.error}
                    </p>
                  )}
                  {run.turns?.map((turn) => (
                    <div
                      key={turn.id}
                      className="grid gap-3 border-b p-3 text-xs last:border-0 md:grid-cols-3"
                    >
                      <div>
                        <p className="mb-1 text-muted-foreground">
                          {turn.identifier} · 요청
                        </p>
                        <pre className="whitespace-pre-wrap break-words font-sans">
                          {turn.request_body}
                        </pre>
                      </div>
                      <div>
                        <p className="mb-1 text-muted-foreground">
                          실제 응답{" "}
                          {turn.response_status
                            ? `(${turn.response_status})`
                            : ""}
                        </p>
                        <pre className="whitespace-pre-wrap break-words font-sans">
                          {turn.error ?? turn.actual_output}
                        </pre>
                      </div>
                      <div>
                        <p className="mb-1 text-muted-foreground">기대 응답</p>
                        <pre className="whitespace-pre-wrap break-words font-sans">
                          {turn.expected_output}
                        </pre>
                        <Badge
                          className="mt-2"
                          variant={turn.passed ? "secondary" : "destructive"}
                        >
                          {turn.score.toFixed(3)}점
                        </Badge>
                        {turn.reason && (
                          <p className="mt-2 text-muted-foreground">
                            {turn.reason}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </article>
              ))}
              {runCount > RUNS_PER_PAGE && (
                <div className="flex items-center justify-between gap-3 pt-2 text-xs text-muted-foreground">
                  <span>
                    총 {runCount.toLocaleString()}건 · {runPage + 1}/
                    {Math.ceil(runCount / RUNS_PER_PAGE)} 페이지
                  </span>
                  <div className="flex gap-1">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={runPage === 0}
                      onClick={() =>
                        setRunPage((value) => Math.max(0, value - 1))
                      }
                    >
                      <ChevronLeft /> 이전
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={(runPage + 1) * RUNS_PER_PAGE >= runCount}
                      onClick={() => setRunPage((value) => value + 1)}
                    >
                      다음 <ChevronRight />
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
