import axios from "axios"
import { Download, Play, Plus, Save, Trash2, Upload } from "lucide-react"
import {
  type ChangeEvent,
  type FormEvent,
  useCallback,
  useEffect,
  useState,
} from "react"

import { PageHeader } from "@/components/Common/PageHeader"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

type DatasetRow = { id: string; input: string; expected_output: string }
type Dataset = {
  id: string
  name: string
  description: string | null
  evaluation_type: string
  endpoint_id: string | null
  body_template: string
  response_path: string | null
  threshold: number
  evaluator: "deepeval" | "local"
  row_count: number
  rows: DatasetRow[]
}
type RunRow = {
  id: string
  input: string
  expected_output: string
  actual_output: string
  response_status: number | null
  score: number
  passed: boolean
  error: string | null
}
type Run = {
  id: string
  created_at: string
  total: number
  passed: number
  average_score: number
  geval_available: boolean
  rows?: RunRow[]
}
type FormState = {
  name: string
  description: string
  endpoint_id: string
  body_template: string
  response_path: string
  threshold: number
  evaluator: "deepeval" | "local"
}

type SingleTurnWorkspaceProps = {
  evaluationType?: "single_turn" | "multi_turn"
  title?: string
  description?: string
  inputLabel?: string
  inputPlaceholder?: string
}

const emptyForm: FormState = {
  name: "새 싱글턴 데이터셋",
  description: "",
  endpoint_id: "",
  body_template: '{\n  "input": "{{input}}"\n}',
  response_path: "",
  threshold: 0.7,
  evaluator: "deepeval",
}

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? "" })
api.interceptors.request.use((config) => {
  config.headers.Authorization = `Bearer ${localStorage.getItem("access_token") ?? ""}`
  return config
})

const toForm = (dataset: Dataset): FormState => ({
  name: dataset.name,
  description: dataset.description ?? "",
  endpoint_id: dataset.endpoint_id ?? "",
  body_template: dataset.body_template,
  response_path: dataset.response_path ?? "",
  threshold: dataset.threshold,
  evaluator: dataset.evaluator,
})

export function SingleTurnWorkspace({
  evaluationType = "single_turn",
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
  const [endpoints, setEndpoints] = useState<
    { id: string; name: string; base_url: string }[]
  >([])
  const [error, setError] = useState("")
  const [isBusy, setIsBusy] = useState(false)

  const selected = datasets.find((dataset) => dataset.id === selectedId)

  const loadDataset = useCallback(async (datasetId: string) => {
    const { data } = await api.get<Dataset>(
      `/api/v1/evaluations/datasets/${datasetId}`,
    )
    setSelectedId(data.id)
    setForm(toForm(data))
    setRows(data.rows)
  }, [])

  const loadDatasets = useCallback(
    async (requestedId?: string | null) => {
      const { data } = await api.get<{ data: Dataset[] }>(
        "/api/v1/evaluations/datasets",
        { params: { evaluation_type: evaluationType } },
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
    [evaluationType, loadDataset, selectedId],
  )

  const loadRuns = useCallback(async (datasetId: string) => {
    const { data } = await api.get<{ data: Run[] }>(
      `/api/v1/evaluations/datasets/${datasetId}/runs`,
    )
    setRuns(data.data)
  }, [])

  const loadRunDetail = async (runId: string) => {
    if (!selectedId) return
    try {
      const { data } = await api.get<Run>(
        `/api/v1/evaluations/datasets/${selectedId}/runs/${runId}`,
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
    if (selectedId) loadRuns(selectedId).catch(() => setRuns([]))
  }, [loadRuns, selectedId])

  const payload = () => ({
    name: form.name,
    description: form.description || null,
    evaluation_type: evaluationType,
    endpoint_id: form.endpoint_id || null,
    body_template: form.body_template,
    response_path: form.response_path || null,
    threshold: Number(form.threshold),
    evaluator: form.evaluator,
  })

  const handleCreate = async () => {
    try {
      setIsBusy(true)
      setError("")
      const { data } = await api.post<Dataset>("/api/v1/evaluations/datasets", {
        ...payload(),
        rows: [],
      })
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
    if (!selectedId) return handleCreate()
    try {
      setIsBusy(true)
      setError("")
      await api.put(`/api/v1/evaluations/datasets/${selectedId}`, payload())
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
        `/api/v1/evaluations/datasets/${selectedId}/rows`,
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
        `/api/v1/evaluations/datasets/${selectedId}/rows/${row.id}`,
        { input: row.input, expected_output: row.expected_output },
      )
      await loadDataset(selectedId)
    } catch {
      setError("행을 저장하지 못했습니다.")
    }
  }

  const deleteRow = async (rowId: string) => {
    if (!selectedId) return
    await api.delete(`/api/v1/evaluations/datasets/${selectedId}/rows/${rowId}`)
    setRows((current) => current.filter((row) => row.id !== rowId))
    await loadDataset(selectedId)
  }

  const run = async () => {
    if (!selectedId) return setError("실행할 데이터셋을 먼저 저장해 주세요.")
    try {
      setIsBusy(true)
      setError("")
      const { data } = await api.post<Run>(
        `/api/v1/evaluations/datasets/${selectedId}/run`,
      )
      await loadRuns(selectedId)
      await loadRunDetail(data.id)
    } catch (requestError) {
      const detail = axios.isAxiosError(requestError)
        ? requestError.response?.data?.detail
        : null
      setError(detail ?? "외부 API 평가 실행에 실패했습니다.")
    } finally {
      setIsBusy(false)
    }
  }

  const deleteDataset = async () => {
    if (!selectedId || !confirm("이 데이터셋과 실행 이력을 삭제할까요?")) return
    await api.delete(`/api/v1/evaluations/datasets/${selectedId}`)
    await loadDatasets(null)
    setRuns([])
  }

  const downloadSample = () => {
    const sample = [
      {
        input: "서울의 오늘 날씨를 알려줘",
        expected_output: "서울의 오늘 날씨는 맑음입니다.",
      },
      {
        input: "서비스 환불 정책을 알려줘",
        expected_output: "환불 정책 안내",
      },
    ]
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(sample, null, 2)], {
        type: "application/json",
      }),
    )
    const link = document.createElement("a")
    link.href = url
    link.download = "evaluation-dataset-sample.json"
    link.click()
    URL.revokeObjectURL(url)
  }

  const uploadRows = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ""
    if (!file) return
    if (!selectedId) {
      setError("JSON을 업로드하기 전에 데이터셋을 먼저 생성해 주세요.")
      return
    }
    try {
      setIsBusy(true)
      setError("")
      const formData = new FormData()
      formData.append("file", file)
      const { data } = await api.post<{ imported: number; row_count: number }>(
        `/api/v1/evaluations/datasets/${selectedId}/import`,
        formData,
      )
      await loadDatasets(selectedId)
      setError(
        `${data.imported.toLocaleString()}개 행을 업로드했습니다. 전체 ${data.row_count.toLocaleString()}개 행`,
      )
    } catch (uploadError) {
      setError(
        uploadError instanceof Error
          ? uploadError.message
          : "JSON 업로드에 실패했습니다.",
      )
    } finally {
      setIsBusy(false)
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
                className={`w-full rounded-md px-3 py-2 text-left text-sm ${dataset.id === selectedId ? "bg-cyan-400/12 text-cyan-500" : "hover:bg-muted"}`}
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
                placeholder="응답 JSON 경로 (예: data.answer)"
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
                <option value="deepeval">DeepEval GEval · 자연어 품질</option>
                <option value="local">Local baseline · 빠른 비교</option>
              </select>
              <textarea
                className="min-h-32 rounded-md border bg-transparent p-3 font-mono text-xs md:col-span-2"
                value={form.body_template}
                aria-label="Request body template"
                onChange={(event) =>
                  setForm({ ...form, body_template: event.target.value })
                }
              />
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
                  입력하세요. JSON 배열 또는 <code>{'{ "data": [...] }'}</code>
                  형식을 최대 100MB까지 업로드할 수 있습니다.
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

          <section className="console-surface p-5">
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
                  <button
                    type="button"
                    className="flex w-full items-center justify-between border-b px-4 py-3 text-left text-sm hover:bg-muted/40"
                    onClick={() => {
                      if (!savedRun.rows) void loadRunDetail(savedRun.id)
                    }}
                  >
                    <span>
                      {new Date(savedRun.created_at).toLocaleString()}
                    </span>
                    <span className="flex gap-2">
                      <Badge variant="secondary">
                        통과 {savedRun.passed}/{savedRun.total}
                      </Badge>
                      <Badge variant="outline">
                        평균 {Math.round(savedRun.average_score * 100)}%
                      </Badge>
                    </span>
                  </button>
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
                        <Badge
                          className="mt-2"
                          variant={row.passed ? "secondary" : "destructive"}
                        >
                          {Math.round(row.score * 100)}%
                        </Badge>
                      </div>
                    </div>
                  ))}
                </article>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
