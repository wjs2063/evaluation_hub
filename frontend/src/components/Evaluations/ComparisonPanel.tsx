import axios from "axios"
import { Download, Play, Trash2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"

type Props = { evaluationMode: "single_turn" | "multi_turn"; targetId: string }
type Choice = { id: string; name: string }
type Comparison = {
  id: string
  status: string
  comparison_mode: string
  comparable_count: number
  winner_a_count: number
  winner_b_count: number
  tie_count: number
  results: Record<string, unknown>[]
  created_at?: string
}

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? "" })
api.interceptors.request.use((config) => {
  config.headers.Authorization = `Bearer ${localStorage.getItem("access_token") ?? ""}`
  return config
})

export function ComparisonPanel({ evaluationMode, targetId }: Props) {
  const [endpoints, setEndpoints] = useState<Choice[]>([])
  const [profiles, setProfiles] = useState<Choice[]>([])
  const [endpointA, setEndpointA] = useState("")
  const [endpointB, setEndpointB] = useState("")
  const [profileId, setProfileId] = useState("")
  const [mode, setMode] = useState("hybrid")
  const [comparison, setComparison] = useState<Comparison | null>(null)
  const [comparisons, setComparisons] = useState<Comparison[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    Promise.all([
      api.get<{ data: Choice[] }>("/api/v1/evaluations/endpoints", {
        params: { limit: 200 },
      }),
      api.get<{ data: Choice[] }>("/api/v1/evaluations/metric-profiles", {
        params: { limit: 200, evaluation_mode: evaluationMode },
      }),
    ])
      .then(([endpointResult, profileResult]) => {
        setEndpoints(endpointResult.data.data)
        setProfiles(profileResult.data.data)
        setEndpointA((value) => value || endpointResult.data.data[0]?.id || "")
        setEndpointB((value) => value || endpointResult.data.data[1]?.id || "")
        setProfileId((value) => value || profileResult.data.data[0]?.id || "")
      })
      .catch(() => setError("A/B 선택 항목을 불러오지 못했습니다."))
  }, [evaluationMode])

  const loadComparisons = useCallback(async () => {
    if (!targetId) {
      setComparisons([])
      return
    }
    const resource =
      evaluationMode === "single_turn"
        ? "single-turn/datasets"
        : "multi-turn/datasets"
    const { data } = await api.get<{ data: Comparison[]; count: number }>(
      `/api/v1/evaluations/${resource}/${targetId}/comparisons`,
      { params: { limit: 10 } },
    )
    setComparisons(data.data)
  }, [evaluationMode, targetId])

  useEffect(() => {
    loadComparisons().catch(() =>
      setError("저장된 A/B 비교 목록을 불러오지 못했습니다."),
    )
  }, [loadComparisons])

  const run = async () => {
    if (!targetId) return setError("먼저 테스트셋을 저장해 주세요.")
    if (!endpointA || !endpointB || endpointA === endpointB)
      return setError("서로 다른 활성 엔드포인트 A와 B를 선택하세요.")
    if (!profileId)
      return setError("평가 유형에 맞는 메트릭 프로필을 선택하세요.")
    try {
      setBusy(true)
      setError("")
      const resource =
        evaluationMode === "single_turn"
          ? "single-turn/datasets"
          : "multi-turn/datasets"
      const { data } = await api.post<Comparison>(
        `/api/v1/evaluations/${resource}/${targetId}/comparisons`,
        {
          endpoint_a_id: endpointA,
          endpoint_b_id: endpointB,
          metric_profile_id: profileId,
          comparison_mode: mode,
        },
      )
      setComparison(data)
      await loadComparisons()
    } catch (requestError) {
      setError(
        axios.isAxiosError(requestError) &&
          typeof requestError.response?.data?.detail === "string"
          ? requestError.response.data.detail
          : "A/B 비교 실행에 실패했습니다.",
      )
    } finally {
      setBusy(false)
    }
  }

  const download = async () => {
    if (!comparison) return
    const response = await api.get(
      `/api/v1/evaluations/comparisons/${comparison.id}/report`,
      { responseType: "blob" },
    )
    const url = URL.createObjectURL(response.data)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `comparison-report-${comparison.id}.html`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const remove = async () => {
    if (!comparison || !window.confirm("이 비교 결과를 삭제할까요?")) return
    await api.delete(`/api/v1/evaluations/comparisons/${comparison.id}`)
    setComparison(null)
    await loadComparisons()
  }

  return (
    <section
      className="console-surface p-4"
      aria-labelledby={`comparison-${evaluationMode}`}
    >
      <div className="flex flex-wrap items-end gap-3">
        <div className="mr-auto">
          <h2
            id={`comparison-${evaluationMode}`}
            className="text-sm font-semibold"
          >
            엔드포인트 A/B 비교평가
          </h2>
          <p className="text-xs text-muted-foreground">
            절대점수와 Arena 승패는 별도 의미로 보존됩니다.
          </p>
        </div>
        {[
          ["엔드포인트 A", endpointA, setEndpointA],
          ["엔드포인트 B", endpointB, setEndpointB],
        ].map(([label, value, setter]) => (
          <label key={label as string} className="space-y-1 text-xs">
            <span>{label as string}</span>
            <select
              className="block h-9 rounded-md border bg-background px-2"
              value={value as string}
              onChange={(event) =>
                (setter as (value: string) => void)(event.target.value)
              }
            >
              <option value="">선택</option>
              {endpoints.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        ))}
        <label className="space-y-1 text-xs">
          <span>메트릭 프로필</span>
          <select
            className="block h-9 rounded-md border bg-background px-2"
            value={profileId}
            onChange={(event) => setProfileId(event.target.value)}
          >
            <option value="">선택</option>
            {profiles.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-xs">
          <span>비교 모드</span>
          <select
            className="block h-9 rounded-md border bg-background px-2"
            value={mode}
            onChange={(event) => setMode(event.target.value)}
          >
            <option value="absolute">절대</option>
            <option value="relative">상대</option>
            <option value="hybrid">혼합</option>
          </select>
        </label>
        <Button type="button" onClick={run} disabled={busy}>
          <Play />
          {busy ? "실행 중…" : "A/B 실행"}
        </Button>
      </div>
      {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
      {comparison && (
        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
          <strong>{comparison.status}</strong>
          <span>비교 가능 {comparison.comparable_count}</span>
          <span>A 승 {comparison.winner_a_count}</span>
          <span>B 승 {comparison.winner_b_count}</span>
          <span>동점 {comparison.tie_count}</span>
          <Button type="button" size="sm" variant="outline" onClick={download}>
            <Download />
            HTML 리포트
          </Button>
          <Button
            type="button"
            size="sm"
            variant="destructive"
            onClick={remove}
          >
            <Trash2 /> 삭제
          </Button>
        </div>
      )}
      <div className="mt-4 border-t pt-3">
        <p className="text-xs font-semibold">저장된 비교</p>
        {comparisons.length === 0 ? (
          <p className="mt-2 text-xs text-muted-foreground">
            저장된 비교 결과가 없습니다.
          </p>
        ) : (
          <div className="mt-2 flex flex-wrap gap-2">
            {comparisons.map((item) => (
              <Button
                key={item.id}
                type="button"
                size="sm"
                variant={comparison?.id === item.id ? "secondary" : "outline"}
                onClick={async () => {
                  const { data } = await api.get<Comparison>(
                    `/api/v1/evaluations/comparisons/${item.id}`,
                  )
                  setComparison(data)
                }}
              >
                {item.comparison_mode} · {item.status}
              </Button>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
