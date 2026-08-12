import axios from "axios"
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileDown,
  Play,
  Plus,
  Save,
  Trash2,
  Upload,
} from "lucide-react"
import {
  type ChangeEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useState,
} from "react"

import {
  type EvaluationMetricProfilePublic,
  EvaluationsService,
} from "@/client"
import { PageHeader } from "@/components/Common/PageHeader"
import {
  EvaluationDetails,
  type EvaluationMetric,
} from "@/components/Evaluations/EvaluationDetails"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

type DatasetRow = { id: string; input: string; expected_output: string }
type Dataset = {
  id: string
  name: string
  description: string | null
  evaluation_type: "single_turn"
  endpoint_id: string | null
  metric_profile_id: string | null
  body_template: string
  response_path: string | null
  threshold: number
  evaluator: "deepeval" | "local"
  row_count: number
  rows: DatasetRow[]
  created_by_id: string | null
  updated_by_id: string | null
  created_at: string
  updated_at: string
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
}
type Run = {
  id: string
  created_at: string
  total: number
  passed: number
  average_score: number
  geval_available: boolean
  dataset_name: string | null
  dataset_description: string | null
  executor_name: string | null
  rows?: RunRow[]
}
type EvaluationJob = {
  id: string
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled"
  run_id: string | null
  error: string | null
}
type FormState = {
  name: string
  description: string
  endpoint_id: string
  metric_profile_id: string
  body_template: string
  response_path: string
  threshold: number
  evaluator: "deepeval" | "local"
}

type SingleTurnWorkspaceProps = {
  title?: string
  description?: string
  inputLabel?: string
  inputPlaceholder?: string
}

const emptyForm: FormState = {
  name: "새 싱글턴 데이터셋",
  description: "",
  endpoint_id: "",
  metric_profile_id: "",
  body_template:
    '{\n  "message": "{{input}}",\n  "system_prompt": null,\n  "history": []\n}',
  response_path: "",
  threshold: 0.7,
  evaluator: "deepeval",
}

const RUNS_PER_PAGE = 20

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? "" })
api.interceptors.request.use((config) => {
  config.headers.Authorization = `Bearer ${localStorage.getItem("access_token") ?? ""}`
  return config
})

const waitForJob = async (jobId: string): Promise<EvaluationJob> => {
  const deadline = Date.now() + 30 * 60 * 1000
  while (Date.now() < deadline) {
    const { data } = await api.get<EvaluationJob>(
      `/api/v1/evaluations/jobs/${jobId}`,
    )
    if (["succeeded", "failed", "cancelled"].includes(data.status)) return data
    await new Promise((resolve) => window.setTimeout(resolve, 1000))
  }
  throw new Error("평가 작업 대기 시간을 초과했습니다.")
}

const toForm = (dataset: Dataset): FormState => ({
  name: dataset.name,
  description: dataset.description ?? "",
  endpoint_id: dataset.endpoint_id ?? "",
  metric_profile_id: dataset.metric_profile_id ?? "",
  body_template: dataset.body_template,
  response_path: dataset.response_path ?? "",
  threshold: dataset.threshold,
  evaluator: dataset.evaluator,
})

export function SingleTurnWorkspace({
  title = "싱글턴 평가",
  description = "저장한 입력값을 외부 API에 전달하고, 추출한 응답과 기대값을 비교합니다.",
  inputLabel = "Input (API에 전달할 값)",
  inputPlaceholder = "예: 서울의 오늘 날씨를 알려줘",
}: SingleTurnWorkspaceProps) {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(emptyForm)
  const [rows, setRows] = useState<DatasetRow[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [runCount, setRunCount] = useState(0)
  const [runPage, setRunPage] = useState(0)
  const [endpoints, setEndpoints] = useState<
    { id: string; name: string; base_url: string }[]
  >([])
  const [metricProfiles, setMetricProfiles] = useState<
    EvaluationMetricProfilePublic[]
  >([])
  const [error, setError] = useState("")
  const [isBusy, setIsBusy] = useState(false)

  const selected = datasets.find((dataset) => dataset.id === selectedId)

  const loadDataset = useCallback(async (datasetId: string) => {
    const { data } = await api.get<Dataset>(
      `/api/v1/evaluations/single-turn/datasets/${datasetId}`,
    )
    setSelectedId(data.id)
    setRunPage(0)
    setForm(toForm(data))
    setRows(data.rows)
  }, [])

  const loadDatasets = useCallback(
    async (requestedId?: string | null) => {
      const { data } = await api.get<{ data: Dataset[] }>(
        "/api/v1/evaluations/single-turn/datasets",
      )
      setDatasets(data.data)
      const nextId = requestedId === undefined ? selectedId : requestedId
      const next = data.data.find((item) => item.id === nextId) ?? data.data[0]
      if (next) {
        await loadDataset(next.id)
      } else {
        setSelectedId(null)
        setForm(emptyForm)
        setRows([])
      }
    },
    [loadDataset, selectedId],
  )

  const loadRuns = useCallback(async (datasetId: string, page = 0) => {
    const { data } = await api.get<{ data: Run[]; count: number }>(
      `/api/v1/evaluations/single-turn/datasets/${datasetId}/runs`,
      { params: { offset: page * RUNS_PER_PAGE, limit: RUNS_PER_PAGE } },
    )
    setRuns(data.data)
    setRunCount(data.count)
  }, [])

  const loadRunDetail = async (runId: string) => {
    if (!selectedId) return
    try {
      const { data } = await api.get<Run>(
        `/api/v1/evaluations/single-turn/datasets/${selectedId}/runs/${runId}`,
      )
      setRuns((current) =>
        current.map((run) => (run.id === runId ? data : run)),
      )
    } catch {
      setError("실행 상세 결과를 불러오지 못했습니다.")
    }
  }

  useEffect(() => {
    loadDatasets(null).catch(() =>
      setError("저장된 데이터셋을 불러오지 못했습니다."),
    )
  }, [loadDatasets])

  useEffect(() => {
    api
      .get<{ data: { id: string; name: string; base_url: string }[] }>(
        "/api/v1/evaluations/endpoints",
      )
      .then(({ data }) => setEndpoints(data.data))
      .catch(() => setError("허용된 A 서버 목록을 불러오지 못했습니다."))
  }, [])

  useEffect(() => {
    EvaluationsService.readMetricProfiles()
      .then((response) =>
        setMetricProfiles(
          response.data.filter((profile) => profile.is_active !== false),
        ),
      )
      .catch(() => setError("평가 프로필 목록을 불러오지 못했습니다."))
  }, [])

  useEffect(() => {
    if (selectedId) {
      loadRuns(selectedId, runPage).catch(() => setRuns([]))
    }
  }, [loadRuns, runPage, selectedId])

  const payload = () => ({
    name: form.name,
    description: form.description || null,
    evaluation_type: "single_turn" as const,
    endpoint_id: form.endpoint_id || null,
    metric_profile_id:
      form.evaluator === "deepeval" ? form.metric_profile_id || null : null,
    body_template: form.body_template,
    response_path: form.response_path || null,
    threshold: Number(form.threshold),
    evaluator: form.evaluator,
  })

  const handleCreate = async () => {
    try {
      setIsBusy(true)
      setError("")
      const { data } = await api.post<Dataset>(
        "/api/v1/evaluations/single-turn/datasets",
        { ...payload(), rows: [] },
      )
      await loadDatasets(data.id)
    } catch (requestError) {
      const detail = axios.isAxiosError(requestError)
        ? requestError.response?.data?.detail
        : null
      setError(detail ?? "데이터셋 생성에 실패했습니다.")
    } finally {
      setIsBusy(false)
    }
  }

  const handleSave = async (event: FormEvent) => {
    event.preventDefault()
    try {
      JSON.parse(form.body_template)
    } catch {
      setError(
        '요청 JSON 템플릿의 문법을 확인해 주세요. 예: {"message":"{{input}}","history":[]}',
      )
      return
    }
    if (!selectedId) return handleCreate()
    try {
      setIsBusy(true)
      setError("")
      await api.put(
        `/api/v1/evaluations/single-turn/datasets/${selectedId}`,
        payload(),
      )
      await loadDatasets(selectedId)
    } catch (requestError) {
      const detail = axios.isAxiosError(requestError)
        ? requestError.response?.data?.detail
        : null
      setError(detail ?? "설정 저장에 실패했습니다.")
    } finally {
      setIsBusy(false)
    }
  }

  const addRow = async () => {
    if (!selectedId) return setError("먼저 데이터셋 설정을 저장해 주세요.")
    try {
      const { data } = await api.post<DatasetRow>(
        `/api/v1/evaluations/single-turn/datasets/${selectedId}/rows`,
        { input: "", expected_output: "" },
      )
      setRows((current) => [...current, data])
      await loadDataset(selectedId)
    } catch {
      setError("행을 추가하지 못했습니다.")
    }
  }

  const saveRow = async (row: DatasetRow) => {
    if (!selectedId) return
    try {
      await api.put(
        `/api/v1/evaluations/single-turn/datasets/${selectedId}/rows/${row.id}`,
        { input: row.input, expected_output: row.expected_output },
      )
      await loadDataset(selectedId)
    } catch {
      setError("행을 저장하지 못했습니다.")
    }
  }

  const deleteRow = async (rowId: string) => {
    if (!selectedId) return
    await api.delete(
      `/api/v1/evaluations/single-turn/datasets/${selectedId}/rows/${rowId}`,
    )
    setRows((current) => current.filter((row) => row.id !== rowId))
    await loadDataset(selectedId)
  }

  const run = async () => {
    if (!selectedId) return setError("실행할 데이터셋을 먼저 저장해 주세요.")
    try {
      setIsBusy(true)
      setError("")
      const { data: queuedJob } = await api.post<EvaluationJob>(
        `/api/v1/evaluations/single-turn/datasets/${selectedId}/run`,
      )
      const job = await waitForJob(queuedJob.id)
      if (job.status !== "succeeded" || !job.run_id) {
        throw new Error(job.error ?? "평가 작업이 실패했습니다.")
      }
      setRunPage(0)
      await loadRuns(selectedId, 0)
      await loadRunDetail(job.run_id)
    } catch (requestError) {
      const detail = axios.isAxiosError(requestError)
        ? requestError.response?.data?.detail
        : requestError instanceof Error
          ? requestError.message
          : null
      setError(detail ?? "외부 API 평가 실행에 실패했습니다.")
    } finally {
      setIsBusy(false)
    }
  }

  const deleteDataset = async () => {
    if (!selectedId || !confirm("이 데이터셋과 실행 이력을 삭제할까요?")) return
    await api.delete(`/api/v1/evaluations/single-turn/datasets/${selectedId}`)
    await loadDatasets(null)
    setRuns([])
  }

  const downloadRunReport = async (runId: string) => {
    if (!selectedId) return
    try {
      const { data } = await api.get<Blob>(
        `/api/v1/evaluations/single-turn/datasets/${selectedId}/runs/${runId}/report.html`,
        { responseType: "blob" },
      )
      const url = URL.createObjectURL(data)
      const link = document.createElement("a")
      link.href = url
      link.download = `evaluation-report-${runId}.html`
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      setError("HTML 결과지를 다운로드하지 못했습니다.")
    }
  }

  const downloadSample = () => {
    const endpointId = form.endpoint_id || endpoints[0]?.id
    const metricProfileId = form.metric_profile_id || metricProfiles[0]?.id
    const sample = {
      name: "고객 응답 품질 테스트",
      description: "외부 API 응답을 기대 결과와 비교하는 싱글턴 테스트셋",
      test_type: "single_turn",
      endpoint_id: endpointId ?? "00000000-0000-0000-0000-000000000000",
      metric_profile_id:
        metricProfileId ?? "00000000-0000-0000-0000-000000000000",
      threshold: 0.7,
      evaluator: "deepeval",
      cases: [
        {
          input: "서울의 오늘 날씨를 알려줘",
          request: {
            headers: { "Content-Type": "application/json" },
            body: {
              message: "서울의 오늘 날씨를 알려줘",
              system_prompt: null,
              history: [],
            },
            actual_output_json_pointer: "/answer",
          },
          expected_output: "서울의 오늘 날씨는 맑음입니다.",
        },
        {
          input: "서비스 환불 정책을 알려줘",
          request: {
            headers: { "Content-Type": "application/json" },
            body: { message: "서비스 환불 정책을 알려줘" },
            actual_output_json_pointer: null,
          },
          expected_output: "환불 정책 안내",
        },
      ],
    }
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(sample, null, 2)], {
        type: "application/json",
      }),
    )
    const link = document.createElement("a")
    link.href = url
    link.download = "single-turn-dataset-sample.json"
    link.click()
    URL.revokeObjectURL(url)
  }

  const uploadRows = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ""
    if (!file) return
    try {
      setIsBusy(true)
      setError("")
      const formData = new FormData()
      formData.append("file", file)
      const { data } = await api.post<Dataset>(
        "/api/v1/evaluations/single-turn/datasets/import",
        formData,
      )
      await loadDatasets(data.id)
      setError(
        `${data.row_count.toLocaleString()}개 case를 가진 테스트셋을 등록했습니다.`,
      )
    } catch (uploadError) {
      const detail = axios.isAxiosError(uploadError)
        ? uploadError.response?.data?.detail
        : null
      setError(detail ?? "싱글턴 테스트셋 JSON 형식을 확인해 주세요.")
    } finally {
      setIsBusy(false)
    }
  }

  const downloadDataset = async () => {
    if (!selectedId) return
    try {
      const { data } = await api.get<Blob>(
        `/api/v1/evaluations/single-turn/datasets/${selectedId}/export`,
        { responseType: "blob" },
      )
      const url = URL.createObjectURL(data)
      const link = document.createElement("a")
      link.href = url
      link.download = `single-turn-dataset-${selectedId}.json`
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      setError("등록된 테스트셋 JSON을 다운로드하지 못했습니다.")
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Evaluation workspace"
        title={title}
        description={description}
      />
      {error && (
        <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="console-surface h-fit p-3">
          <Button
            className="mb-3 w-full"
            size="sm"
            onClick={() => {
              setSelectedId(null)
              setForm({
                ...emptyForm,
                name: "새 싱글턴 데이터셋",
              })
              setRows([])
              setRuns([])
            }}
          >
            <Plus /> 새 데이터셋
          </Button>
          <div className="space-y-1">
            {datasets.map((dataset) => (
              <button
                key={dataset.id}
                type="button"
                onClick={() => {
                  loadDataset(dataset.id).catch(() =>
                    setError("데이터셋을 불러오지 못했습니다."),
                  )
                }}
                className={`w-full rounded-md px-3 py-2 text-left text-sm ${dataset.id === selectedId ? "bg-primary/10 text-primary" : "hover:bg-muted"}`}
              >
                <p className="truncate font-medium">{dataset.name}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {dataset.row_count.toLocaleString()} rows
                </p>
              </button>
            ))}
          </div>
        </aside>
        <div className="space-y-4">
          <form className="console-surface p-5" onSubmit={handleSave}>
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold">
                  테스트 및 외부 API 설정
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  본문의 <code>{"{{input}}"}</code> 자리에 각 행의 input이
                  삽입됩니다. 요청은 JSON 본문을 가진 <code>POST</code>로
                  전송됩니다. 관리자가 허용한 A 서버와 응답 경로를 저장하세요.
                  인증 헤더는 관리자 설정에서 암호화되어 관리됩니다.
                </p>
              </div>
              {selected && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={deleteDataset}
                >
                  <Trash2 />
                </Button>
              )}
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <Input
                value={form.name}
                placeholder="테스트 이름"
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
              />
              <Input
                value={form.description}
                placeholder="테스트 설명"
                onChange={(event) =>
                  setForm({ ...form, description: event.target.value })
                }
              />
              <select
                aria-label="Allowed A server"
                className="h-9 rounded-md border bg-transparent px-3 text-sm"
                value={form.endpoint_id}
                onChange={(event) =>
                  setForm({ ...form, endpoint_id: event.target.value })
                }
              >
                <option value="">A 서버를 선택하세요</option>
                {endpoints.map((endpoint) => (
                  <option key={endpoint.id} value={endpoint.id}>
                    {endpoint.name} · {endpoint.base_url}
                  </option>
                ))}
              </select>
              <Input
                value={form.response_path}
                placeholder="Actual output JSON Pointer (예: /data/answer, 비우면 전체)"
                onChange={(event) =>
                  setForm({ ...form, response_path: event.target.value })
                }
              />
              <select
                aria-label="Evaluator"
                className="h-9 rounded-md border bg-transparent px-3 text-sm"
                value={form.evaluator}
                onChange={(event) =>
                  setForm({
                    ...form,
                    evaluator: event.target.value as "deepeval" | "local",
                  })
                }
              >
                <option value="deepeval">DeepEval · 고정 공식 지표</option>
                <option value="local">Local baseline · 빠른 비교</option>
              </select>
              {form.evaluator === "deepeval" && (
                <label className="space-y-1 text-sm">
                  <span>평가지표 프로필</span>
                  <select
                    aria-label="DeepEval metric profile"
                    className="h-9 w-full rounded-md border bg-transparent px-3 text-sm"
                    value={form.metric_profile_id}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        metric_profile_id: event.target.value,
                      })
                    }
                  >
                    <option value="" disabled>
                      평가에 사용할 프로필을 선택하세요
                    </option>
                    {metricProfiles.map((profile) => (
                      <option key={profile.id} value={profile.id}>
                        {profile.name} · v{profile.version} ·{" "}
                        {(profile.metrics ?? []).length}개 지표
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="space-y-2 md:col-span-2">
                <span className="text-sm font-medium">요청 JSON 템플릿</span>
                <textarea
                  className="min-h-40 w-full rounded-md border bg-transparent p-3 font-mono text-xs"
                  value={form.body_template}
                  aria-label="Request body template"
                  spellCheck={false}
                  onChange={(event) =>
                    setForm({ ...form, body_template: event.target.value })
                  }
                />
                <span className="block text-xs text-muted-foreground">
                  전송할 JSON 구조를 직접 입력하세요. 객체·배열 안의{" "}
                  <code>{"{{input}}"}</code>는 실행 시 각 데이터셋 행의
                  Input으로 치환됩니다.
                </span>
              </label>
            </div>
            <div className="mt-4 flex justify-end">
              <Button type="submit" disabled={isBusy}>
                <Save /> {selected ? "설정 저장" : "데이터셋 생성"}
              </Button>
            </div>
          </form>

          <section className="console-surface p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold">데이터셋 행</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  <strong>Input</strong>에는 API에 보낼 문장을,{" "}
                  <strong>Expected output</strong>에는 기대하는 정답을
                  입력하세요. 업로드 문서는 <code>test_type</code>, 요청
                  headers/body, 응답 JSON Pointer, <code>cases</code>를 포함해야
                  하며 최대 100MB까지 허용됩니다.
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={downloadSample}
                >
                  <Download /> JSON 샘플
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!selectedId}
                  onClick={downloadDataset}
                >
                  <FileDown /> 테스트셋 JSON
                </Button>
                <Button type="button" variant="outline" size="sm" asChild>
                  <label className="cursor-pointer">
                    <Upload /> JSON 업로드
                    <input
                      className="sr-only"
                      type="file"
                      accept="application/json,.json"
                      onChange={uploadRows}
                    />
                  </label>
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={addRow}
                >
                  <Plus /> 행 추가
                </Button>
              </div>
            </div>
            <div className="mb-3 grid gap-2 px-3 text-xs font-medium text-muted-foreground md:grid-cols-[32px_1fr_1fr_auto_auto]">
              <span>No.</span>
              <span>{inputLabel}</span>
              <span>Expected output (기대하는 정답)</span>
            </div>
            <div className="space-y-3">
              {rows.map((row, index) => (
                <div
                  key={row.id}
                  className="grid gap-2 rounded-md border p-3 md:grid-cols-[32px_1fr_1fr_auto_auto]"
                >
                  <span className="pt-2 text-xs text-muted-foreground">
                    {index + 1}
                  </span>
                  <textarea
                    className="min-h-20 rounded border bg-transparent p-2 text-sm"
                    value={row.input}
                    aria-label={`Input ${index + 1}`}
                    placeholder={inputPlaceholder}
                    onChange={(event) =>
                      setRows(
                        rows.map((item) =>
                          item.id === row.id
                            ? { ...item, input: event.target.value }
                            : item,
                        ),
                      )
                    }
                  />
                  <textarea
                    className="min-h-20 rounded border bg-transparent p-2 text-sm"
                    value={row.expected_output}
                    aria-label={`Expected output ${index + 1}`}
                    placeholder="예: 서울의 오늘 날씨는 맑음입니다."
                    onChange={(event) =>
                      setRows(
                        rows.map((item) =>
                          item.id === row.id
                            ? { ...item, expected_output: event.target.value }
                            : item,
                        ),
                      )
                    }
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    onClick={() => saveRow(row)}
                  >
                    <Save />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => deleteRow(row.id)}
                  >
                    <Trash2 />
                  </Button>
                </div>
              ))}
            </div>
          </section>

          <section id="results" className="console-surface scroll-mt-16 p-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold">실행 및 저장된 결과</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  각 호출의 원본 응답과 비교 점수가 실행 이력에 보관됩니다.
                  GEval은 판정 모델 연결 후 제공됩니다.
                </p>
              </div>
              <Button
                type="button"
                onClick={run}
                disabled={!selectedId || isBusy || rows.length === 0}
              >
                <Play /> {isBusy ? "실행 중…" : "평가 실행"}
              </Button>
            </div>
            <div className="mt-4 space-y-3">
              {rows.length < (selected?.row_count ?? 0) && (
                <p className="rounded-md bg-muted p-3 text-xs text-muted-foreground">
                  대용량 데이터셋은 처음 200개 행만 편집기에 표시됩니다. 전체
                  데이터는 저장되어 평가 실행에 사용됩니다.
                </p>
              )}
              {runs.map((savedRun) => (
                <article key={savedRun.id} className="rounded-md border">
                  <div className="flex items-stretch border-b">
                    <button
                      type="button"
                      className="grid min-w-0 flex-1 gap-2 px-4 py-3 text-left text-sm hover:bg-muted/40 md:grid-cols-[minmax(150px,1fr)_minmax(120px,1fr)_minmax(120px,1fr)_auto] md:items-center"
                      onClick={() => {
                        if (!savedRun.rows) void loadRunDetail(savedRun.id)
                      }}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">
                          {savedRun.dataset_name ??
                            selected?.name ??
                            "품질 테스트"}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {savedRun.dataset_description || "설명 없음"}
                        </span>
                      </span>
                      <span className="text-xs">
                        <span className="block text-muted-foreground">
                          실행자
                        </span>
                        {savedRun.executor_name ?? "-"}
                      </span>
                      <span className="text-xs">
                        <span className="block text-muted-foreground">
                          실행시각
                        </span>
                        {new Date(savedRun.created_at).toLocaleString()}
                      </span>
                      <span className="flex flex-wrap gap-2 md:justify-end">
                        <Badge variant="secondary">
                          통과 {savedRun.passed}/{savedRun.total}
                        </Badge>
                        <Badge variant="outline">
                          점수 {(savedRun.average_score * 100).toFixed(2)}점
                        </Badge>
                      </span>
                    </button>
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-auto rounded-none border-l px-3"
                      aria-label={`Download HTML report ${savedRun.id}`}
                      onClick={() => downloadRunReport(savedRun.id)}
                    >
                      <FileDown />
                      <span className="hidden lg:inline">HTML</span>
                    </Button>
                  </div>
                  {!savedRun.rows && (
                    <p className="px-4 py-3 text-xs text-muted-foreground">
                      클릭하여 행별 실제 응답과 점수를 확인하세요.
                    </p>
                  )}
                  {savedRun.rows?.map((row) => (
                    <div
                      key={row.id}
                      className="grid gap-2 border-b p-4 text-xs last:border-0 md:grid-cols-3"
                    >
                      <div>
                        <p className="mb-1 text-muted-foreground">Input</p>
                        <p>{row.input}</p>
                      </div>
                      <div>
                        <p className="mb-1 text-muted-foreground">
                          Actual{" "}
                          {row.response_status && `(${row.response_status})`}
                        </p>
                        <p>{row.error ?? row.actual_output}</p>
                      </div>
                      <div>
                        <p className="mb-1 text-muted-foreground">
                          Expected · score
                        </p>
                        <p>{row.expected_output}</p>
                      </div>
                      <EvaluationDetails
                        className="mt-2 md:col-span-3"
                        score={row.score}
                        passed={row.passed}
                        metrics={row.metrics}
                      />
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
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={runPage === 0}
                      onClick={() =>
                        setRunPage((page) => Math.max(0, page - 1))
                      }
                    >
                      <ChevronLeft /> 이전
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={(runPage + 1) * RUNS_PER_PAGE >= runCount}
                      onClick={() => setRunPage((page) => page + 1)}
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
