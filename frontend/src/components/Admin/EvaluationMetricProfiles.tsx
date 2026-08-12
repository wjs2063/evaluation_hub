import { Plus, Save, Trash2 } from "lucide-react"
import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react"

import {
  ApiError,
  type EvaluationMetricCatalogItem,
  type EvaluationMetricDefinitionCreate,
  type EvaluationMetricProfilePublic,
  type EvaluationMetricType,
  EvaluationsService,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

type ProfileDraft = {
  name: string
  description: string
  is_active: boolean
  metrics: EvaluationMetricDefinitionCreate[]
}

const starterMetrics: EvaluationMetricDefinitionCreate[] = [
  { metric_type: "geval_correctness", weight_percent: 50 },
  { metric_type: "answer_relevancy", weight_percent: 30 },
  { metric_type: "geval_professionalism", weight_percent: 20 },
]

const emptyDraft = (): ProfileDraft => ({
  name: "새 평가 프로필",
  description: "",
  is_active: true,
  metrics: starterMetrics.map((metric) => ({ ...metric })),
})

const toDraft = (profile: EvaluationMetricProfilePublic): ProfileDraft => ({
  name: profile.name,
  description: profile.description ?? "",
  is_active: profile.is_active ?? true,
  metrics: (profile.metrics ?? []).map(({ metric_type, weight_percent }) => ({
    metric_type,
    weight_percent,
  })),
})

const errorMessage = (error: unknown) => {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | undefined)?.detail
    if (typeof detail === "string") return detail
  }
  return "평가 프로필을 저장하지 못했습니다."
}

export function EvaluationMetricProfiles() {
  const [catalog, setCatalog] = useState<EvaluationMetricCatalogItem[]>([])
  const [profiles, setProfiles] = useState<EvaluationMetricProfilePublic[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<ProfileDraft>(emptyDraft)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  const weightTotal = useMemo(
    () => draft.metrics.reduce((sum, metric) => sum + metric.weight_percent, 0),
    [draft.metrics],
  )
  const catalogByType = useMemo(
    () => new Map(catalog.map((item) => [item.metric_type, item])),
    [catalog],
  )

  const load = useCallback(async (requestedId?: string | null) => {
    const [profileResponse, catalogResponse] = await Promise.all([
      EvaluationsService.readMetricProfiles(),
      EvaluationsService.readMetricCatalog(),
    ])
    setProfiles(profileResponse.data)
    setCatalog(catalogResponse.data)
    const next =
      profileResponse.data.find((profile) => profile.id === requestedId) ??
      (requestedId === undefined ? undefined : profileResponse.data[0])
    if (next) {
      setSelectedId(next.id)
      setDraft(toDraft(next))
    }
  }, [])

  useEffect(() => {
    load(null).catch((requestError) => setError(errorMessage(requestError)))
  }, [load])

  const updateMetric = (
    index: number,
    patch: Partial<EvaluationMetricDefinitionCreate>,
  ) => {
    setDraft((current) => ({
      ...current,
      metrics: current.metrics.map((metric, metricIndex) =>
        metricIndex === index ? { ...metric, ...patch } : metric,
      ),
    }))
  }

  const addMetric = () => {
    const selected = new Set(draft.metrics.map((metric) => metric.metric_type))
    const available = catalog.find((item) => !selected.has(item.metric_type))
    if (!available) return
    setDraft((current) => ({
      ...current,
      metrics: [
        ...current.metrics,
        { metric_type: available.metric_type, weight_percent: 1 },
      ],
    }))
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    const types = draft.metrics.map((metric) => metric.metric_type)
    if (!draft.name.trim()) return setError("프로필 이름을 입력하세요.")
    if (draft.metrics.length < 1 || draft.metrics.length > 5)
      return setError(
        "DeepEval 권장 범위에 따라 지표는 1개 이상 5개 이하로 선택하세요.",
      )
    if (new Set(types).size !== types.length)
      return setError("같은 평가지표를 중복 선택할 수 없습니다.")
    if (weightTotal !== 100)
      return setError("지표 가중치 합계는 정확히 100%여야 합니다.")
    try {
      setBusy(true)
      setError("")
      const requestBody = {
        name: draft.name.trim(),
        description: draft.description.trim() || null,
        is_active: draft.is_active,
        metrics: draft.metrics,
      }
      const saved = selectedId
        ? await EvaluationsService.updateMetricProfile({
            profileId: selectedId,
            requestBody,
          })
        : await EvaluationsService.createMetricProfile({ requestBody })
      await load(saved.id)
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="console-surface overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold">DeepEval 평가 프로필</h2>
          <p className="mt-0.5 max-w-3xl text-xs text-muted-foreground">
            공식 문서와 현재 데이터셋 필드가 지원하는 고정 지표만 선택합니다. 각
            지표의 DeepEval 원점수와 이유를 보존하고 서버가 가중 최종 점수를
            계산합니다.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            setSelectedId(null)
            setDraft(emptyDraft())
            setError("")
          }}
        >
          <Plus /> 새 프로필
        </Button>
      </div>
      <div className="grid gap-5 p-5 xl:grid-cols-[280px_minmax(0,1fr)]">
        <div className="space-y-2">
          {profiles.length === 0 && (
            <p className="rounded-md bg-muted p-3 text-sm text-muted-foreground">
              등록된 평가 프로필이 없습니다.
            </p>
          )}
          {profiles.map((profile) => (
            <button
              key={profile.id}
              type="button"
              className={`w-full rounded-md border p-3 text-left ${selectedId === profile.id ? "border-primary bg-primary/5" : "hover:bg-muted/50"}`}
              onClick={() => {
                setSelectedId(profile.id)
                setDraft(toDraft(profile))
                setError("")
              }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{profile.name}</span>
                <Badge variant={profile.is_active ? "secondary" : "outline"}>
                  v{profile.version}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {(profile.metrics ?? []).length}개 지표
              </p>
            </button>
          ))}
        </div>

        <form className="min-w-0 space-y-4" onSubmit={save}>
          <div className="grid gap-3 md:grid-cols-2">
            <label htmlFor="metric-profile-name" className="space-y-1 text-sm">
              <span>프로필 이름</span>
              <Input
                id="metric-profile-name"
                value={draft.name}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
              />
            </label>
            <label
              htmlFor="metric-profile-description"
              className="space-y-1 text-sm"
            >
              <span>설명</span>
              <Input
                id="metric-profile-description"
                value={draft.description}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    description: event.target.value,
                  }))
                }
              />
            </label>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={draft.is_active}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  is_active: event.target.checked,
                }))
              }
            />
            데이터셋에서 선택 가능
          </label>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium">평가지표 · 최대 5개</p>
              <p
                role="status"
                aria-label="평가지표 가중치 합계"
                className={`text-xs ${weightTotal === 100 ? "text-emerald-700 dark:text-emerald-400" : "text-destructive"}`}
              >
                가중치 합계 {weightTotal}% ·{" "}
                {weightTotal === 100
                  ? "저장 가능"
                  : `100%가 되도록 ${weightTotal < 100 ? `${100 - weightTotal}%를 추가` : `${weightTotal - 100}%를 차감`}하세요.`}
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              disabled={
                draft.metrics.length >= 5 ||
                draft.metrics.length >= catalog.length
              }
              onClick={addMetric}
            >
              <Plus /> 지표 추가
            </Button>
          </div>

          <div className="space-y-3">
            {draft.metrics.map((metric, index) => {
              const selected = catalogByType.get(metric.metric_type)
              return (
                <div
                  key={`${index}-${metric.metric_type}`}
                  className="rounded-md border p-4"
                >
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_120px_auto]">
                    <label
                      htmlFor={`metric-${index}-type`}
                      className="space-y-1 text-xs"
                    >
                      <span>DeepEval 평가지표</span>
                      <select
                        id={`metric-${index}-type`}
                        aria-label={`지표 ${index + 1} 타입`}
                        className="h-9 w-full rounded-md border bg-background px-3"
                        value={metric.metric_type}
                        onChange={(event) =>
                          updateMetric(index, {
                            metric_type: event.target
                              .value as EvaluationMetricType,
                          })
                        }
                      >
                        {catalog.map((item) => (
                          <option
                            key={item.metric_type}
                            value={item.metric_type}
                            disabled={draft.metrics.some(
                              (other, otherIndex) =>
                                otherIndex !== index &&
                                other.metric_type === item.metric_type,
                            )}
                          >
                            {item.display_name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label
                      htmlFor={`metric-${index}-weight`}
                      className="space-y-1 text-xs"
                    >
                      <span>가중치 (%)</span>
                      <Input
                        id={`metric-${index}-weight`}
                        aria-label={`${selected?.display_name ?? metric.metric_type} 가중치`}
                        type="number"
                        min={1}
                        max={100}
                        value={metric.weight_percent}
                        onChange={(event) =>
                          updateMetric(index, {
                            weight_percent: Number(event.target.value),
                          })
                        }
                      />
                    </label>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`${selected?.display_name ?? metric.metric_type} 지표 삭제`}
                      disabled={draft.metrics.length === 1}
                      onClick={() =>
                        setDraft((current) => ({
                          ...current,
                          metrics: current.metrics.filter(
                            (_, itemIndex) => itemIndex !== index,
                          ),
                        }))
                      }
                    >
                      <Trash2 />
                    </Button>
                  </div>
                  {selected && (
                    <div className="mt-3 space-y-1 text-xs text-muted-foreground">
                      <p>{selected.description}</p>
                      <p>
                        필요 필드: {selected.required_fields.join(", ")} ·{" "}
                        {selected.uses_llm ? "LLM judge" : "비LLM 결정적 지표"}{" "}
                        ·{" "}
                        {selected.score_direction === "lower_is_better"
                          ? "원점수가 낮을수록 좋음"
                          : "점수가 높을수록 좋음"}
                      </p>
                      <a
                        className="text-primary underline-offset-4 hover:underline"
                        href={selected.docs_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        DeepEval 공식 문서
                      </a>
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" disabled={busy || weightTotal !== 100}>
            <Save />{" "}
            {busy ? "저장 중…" : selectedId ? "새 버전 저장" : "프로필 저장"}
          </Button>
        </form>
      </div>
    </section>
  )
}
