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
  type CustomMetricPlaceholderContract,
  type CustomMetricPublic,
  type EvaluationMetricCatalogItem,
  type EvaluationMetricDefinitionCreate,
  type EvaluationMetricProfilePublic,
  type EvaluationMetricType,
  type EvaluationMode,
  type EvaluationScope,
  EvaluationsService,
} from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

const scopes: Array<{ value: EvaluationScope; label: string }> = [
  {
    value: "quick_upload",
    label: "빠른 업로드",
  },
  {
    value: "single_turn",
    label: "단일턴",
  },
  {
    value: "multi_turn",
    label: "멀티턴",
  },
]

const modeForScope = (scope: EvaluationScope): EvaluationMode =>
  scope === "multi_turn" ? "multi_turn" : "single_turn"

const errorMessage = (error: unknown, fallback: string) => {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | undefined)?.detail
    if (typeof detail === "string") return detail
    if (Array.isArray(detail)) {
      const messages = detail.map((item) => {
        if (!item || typeof item !== "object") return String(item)
        const validation = item as {
          msg?: unknown
          loc?: unknown
          ctx?: {
            evaluation_scope?: unknown
            invalid_tokens?: unknown
            allowed_keys?: unknown
          }
        }
        const message =
          typeof validation.msg === "string" ? validation.msg : fallback
        const location = Array.isArray(validation.loc)
          ? validation.loc[validation.loc.length - 1]
          : undefined
        const context = validation.ctx
        const scope =
          typeof context?.evaluation_scope === "string"
            ? `범위: ${context.evaluation_scope}`
            : ""
        const invalid = Array.isArray(context?.invalid_tokens)
          ? `잘못된 token: ${context.invalid_tokens.map(String).join(", ") || "없음"}`
          : ""
        const allowed = Array.isArray(context?.allowed_keys)
          ? `허용: ${context.allowed_keys.map((key) => `{{${String(key)}}}`).join(", ")}`
          : ""
        const contextMessage = [scope, invalid, allowed]
          .filter(Boolean)
          .join(" · ")
        return `${location ? `${String(location)}: ` : ""}${message}${contextMessage ? `\n${contextMessage}` : ""}`
      })
      if (messages.length > 0) return messages.join("\n")
    }
  }
  return fallback
}

type PromptValidation =
  | { valid: true; requiredKeys: string[] }
  | { valid: false; message: string; invalidTokens: string[] }

const placeholderKey = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/

function validateCustomMetricPrompt(
  prompt: string,
  scope: EvaluationScope,
  contract?: CustomMetricPlaceholderContract,
): PromptValidation {
  if (!contract) {
    return {
      valid: false,
      message: "Backend placeholder 계약을 확인할 수 없어 저장할 수 없습니다.",
      invalidTokens: [],
    }
  }
  const keys: string[] = []
  const malformed: string[] = []
  let cursor = 0
  while (cursor < prompt.length) {
    const opening = prompt.indexOf("{{", cursor)
    const closingBeforeOpening = prompt.indexOf("}}", cursor)
    if (
      closingBeforeOpening !== -1 &&
      (opening === -1 || closingBeforeOpening < opening)
    ) {
      malformed.push("}}")
      cursor = closingBeforeOpening + 2
      continue
    }
    if (opening === -1) break
    const closing = prompt.indexOf("}}", opening + 2)
    if (closing === -1) {
      malformed.push(prompt.slice(opening))
      break
    }
    const token = prompt.slice(opening, closing + 2)
    const key = prompt.slice(opening + 2, closing)
    if (key.includes("{{") || !placeholderKey.test(key)) malformed.push(token)
    else keys.push(key)
    cursor = closing + 2
  }
  const allowed = contract.allowed_keys.map((key) => `{{${key}}}`).join(", ")
  const uniqueMalformed = [...new Set(malformed)]
  if (uniqueMalformed.length > 0) {
    return {
      valid: false,
      invalidTokens: uniqueMalformed,
      message: `placeholder 문법이 올바르지 않습니다. 잘못된 token: ${uniqueMalformed.join(", ")} · 범위: ${scope} · 허용: ${allowed}`,
    }
  }
  const uniqueKeys = [...new Set(keys)]
  if (contract.requires_at_least_one && uniqueKeys.length === 0) {
    return {
      valid: false,
      invalidTokens: [],
      message: `placeholder를 하나 이상 입력하세요. 범위: ${scope} · 허용: ${allowed}`,
    }
  }
  const unsupported = uniqueKeys.filter(
    (key) => !contract.allowed_keys.includes(key),
  )
  if (unsupported.length > 0) {
    return {
      valid: false,
      invalidTokens: unsupported,
      message: `지원하지 않는 placeholder: ${unsupported.map((key) => `{{${key}}}`).join(", ")} · 범위: ${scope} · 허용: ${allowed}`,
    }
  }
  return { valid: true, requiredKeys: uniqueKeys }
}

type CustomDraft = {
  name: string
  description: string
  evaluation_scope: EvaluationScope
  prompt: string
  is_active: boolean
  version?: number
}

const emptyCustom = (scope: EvaluationScope): CustomDraft => ({
  name: "새 CustomMetric",
  description: "",
  evaluation_scope: scope,
  prompt:
    scope === "multi_turn"
      ? "{{role}}과 {{content}}를 바탕으로 전체 대화 품질을 평가하세요."
      : "{{input}}에 대한 {{actual_output}}의 품질을 평가하세요.",
  is_active: true,
})

function CustomMetricsPanel({
  metrics,
  contracts,
  contractError,
  scope,
  reload,
}: {
  metrics: CustomMetricPublic[]
  contracts: CustomMetricPlaceholderContract[]
  contractError: string
  scope: EvaluationScope
  reload: () => Promise<void>
}) {
  const visible = metrics.filter((metric) => metric.evaluation_scope === scope)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<CustomDraft>(() => emptyCustom(scope))
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const contract = contracts.find((item) => item.evaluation_scope === scope)
  const promptValidation = validateCustomMetricPrompt(
    draft.prompt,
    scope,
    contract,
  )

  useEffect(() => {
    setSelectedId(null)
    setDraft((current) => ({ ...current, evaluation_scope: scope }))
    setError("")
  }, [scope])

  const selectMetric = (metric: CustomMetricPublic) => {
    setSelectedId(metric.id)
    setDraft({
      name: metric.name,
      description: metric.description ?? "",
      evaluation_scope: metric.evaluation_scope,
      prompt: metric.prompt,
      is_active: metric.is_active ?? true,
      version: metric.version,
    })
    setError("")
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!promptValidation.valid) {
      setError(promptValidation.message)
      return
    }
    try {
      setBusy(true)
      setError("")
      const requestBody = {
        name: draft.name.trim(),
        description: draft.description.trim() || null,
        evaluation_scope: scope,
        prompt: draft.prompt,
        is_active: draft.is_active,
      }
      const saved = selectedId
        ? await EvaluationsService.updateCustomMetric({
            metricId: selectedId,
            requestBody: { ...requestBody, expected_version: draft.version },
          })
        : await EvaluationsService.createCustomMetric({ requestBody })
      await reload()
      selectMetric(saved)
    } catch (requestError) {
      setError(
        errorMessage(requestError, "CustomMetric을 저장하지 못했습니다."),
      )
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!selectedId) return
    try {
      setBusy(true)
      setError("")
      await EvaluationsService.deleteCustomMetric({ metricId: selectedId })
      setSelectedId(null)
      setDraft(emptyCustom(scope))
      await reload()
    } catch (requestError) {
      setError(
        errorMessage(
          requestError,
          "참조 중인 CustomMetric은 삭제할 수 없습니다.",
        ),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="console-surface overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold">공유 CustomMetric</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            프롬프트의 placeholder는 응답 문자열 치환이 아니라 DeepEval 테스트
            케이스 필드로 안전하게 바인딩됩니다.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            setSelectedId(null)
            setDraft(emptyCustom(scope))
            setError("")
          }}
        >
          <Plus /> 새 CustomMetric
        </Button>
      </div>
      <div className="grid gap-5 p-5 xl:grid-cols-[280px_minmax(0,1fr)]">
        <div className="space-y-2">
          {visible.length === 0 && (
            <p className="rounded-md bg-muted p-3 text-sm text-muted-foreground">
              이 범위에 등록된 CustomMetric이 없습니다.
            </p>
          )}
          {visible.map((metric) => (
            <button
              key={metric.id}
              type="button"
              className={`w-full rounded-md border p-3 text-left ${selectedId === metric.id ? "border-primary bg-primary/5" : "hover:bg-muted/50"}`}
              onClick={() => selectMetric(metric)}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="font-medium">{metric.name}</span>
                <Badge variant={metric.is_active ? "secondary" : "outline"}>
                  v{metric.version}
                </Badge>
              </span>
              <span className="mt-1 block text-xs text-muted-foreground">
                {metric.required_keys.join(", ")}
              </span>
            </button>
          ))}
        </div>
        <form className="min-w-0 space-y-4" onSubmit={save}>
          <div className="grid gap-3 md:grid-cols-2">
            <label htmlFor="custom-metric-name" className="space-y-1 text-sm">
              <span>이름</span>
              <Input
                id="custom-metric-name"
                aria-label="CustomMetric 이름"
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
              htmlFor="custom-metric-description"
              className="space-y-1 text-sm"
            >
              <span>설명</span>
              <Input
                id="custom-metric-description"
                aria-label="CustomMetric 설명"
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
          <label
            htmlFor="custom-metric-prompt"
            className="block space-y-1 text-sm"
          >
            <span>G-Eval 프롬프트</span>
            <textarea
              id="custom-metric-prompt"
              aria-label="CustomMetric G-Eval 프롬프트"
              aria-invalid={!promptValidation.valid}
              aria-describedby="custom-metric-prompt-feedback"
              className="min-h-36 w-full rounded-md border bg-background p-3 font-mono text-xs aria-invalid:border-destructive aria-invalid:ring-destructive/20"
              maxLength={8000}
              value={draft.prompt}
              onChange={(event) =>
                setDraft((current) => ({
                  ...current,
                  prompt: event.target.value,
                }))
              }
            />
            <span id="custom-metric-prompt-feedback" className="block text-xs">
              {contractError ? (
                <span role="alert" className="text-destructive">
                  {contractError}
                </span>
              ) : promptValidation.valid ? (
                <span className="text-emerald-700 dark:text-emerald-400">
                  인식된 key: {promptValidation.requiredKeys.join(", ")}
                </span>
              ) : (
                <span role="alert" className="text-destructive">
                  {promptValidation.message}
                </span>
              )}
            </span>
          </label>
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
            프로필에서 선택 가능
          </label>
          {error && (
            <p
              role="alert"
              className="whitespace-pre-line text-sm text-destructive"
            >
              {error}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              type="submit"
              disabled={
                busy || !promptValidation.valid || Boolean(contractError)
              }
            >
              <Save />{" "}
              {busy ? "저장 중…" : selectedId ? "새 버전 저장" : "저장"}
            </Button>
            {selectedId && (
              <Button
                type="button"
                variant="destructive"
                disabled={busy}
                onClick={() => void remove()}
              >
                <Trash2 /> 삭제
              </Button>
            )}
          </div>
        </form>
      </div>
    </section>
  )
}

type ProfileDraft = {
  name: string
  description: string
  is_active: boolean
  evaluation_scope: EvaluationScope
  metrics: EvaluationMetricDefinitionCreate[]
  version?: number
}

const starterMetrics = (
  scope: EvaluationScope,
): EvaluationMetricDefinitionCreate[] =>
  scope === "multi_turn"
    ? [
        { metric_type: "turn_relevancy", weight_percent: 25 },
        {
          metric_type: "role_adherence",
          weight_percent: 25,
          config: { chatbot_role: "" },
        },
        { metric_type: "knowledge_retention", weight_percent: 25 },
        { metric_type: "conversation_completeness", weight_percent: 25 },
      ]
    : [
        { metric_type: "geval_correctness", weight_percent: 50 },
        { metric_type: "answer_relevancy", weight_percent: 30 },
        { metric_type: "geval_professionalism", weight_percent: 20 },
      ]

const emptyProfile = (scope: EvaluationScope): ProfileDraft => ({
  name: "새 평가 프로필",
  description: "",
  is_active: true,
  evaluation_scope: scope,
  metrics: starterMetrics(scope),
})

const metricIdentity = (metric: EvaluationMetricDefinitionCreate) =>
  metric.custom_metric_id
    ? `custom:${metric.custom_metric_id}`
    : `builtin:${metric.metric_type}`

export function MetricProfilesPanel({
  profiles: suppliedProfiles,
  customMetrics: suppliedCustomMetrics,
  catalog: suppliedCatalog,
  scope: suppliedScope,
  reload: suppliedReload,
}: {
  profiles?: EvaluationMetricProfilePublic[]
  customMetrics?: CustomMetricPublic[]
  catalog?: EvaluationMetricCatalogItem[]
  scope?: EvaluationScope
  reload?: () => Promise<void>
} = {}) {
  const [localProfiles, setLocalProfiles] = useState<
    EvaluationMetricProfilePublic[]
  >([])
  const [localCustom, setLocalCustom] = useState<CustomMetricPublic[]>([])
  const [localCatalog, setLocalCatalog] = useState<
    EvaluationMetricCatalogItem[]
  >([])
  const [localScope, _setLocalScope] = useState<EvaluationScope>("single_turn")
  const scope = suppliedScope ?? localScope
  const profiles = suppliedProfiles ?? localProfiles
  const customMetrics = suppliedCustomMetrics ?? localCustom
  const catalog = suppliedCatalog ?? localCatalog
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<ProfileDraft>(() => emptyProfile(scope))
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  const localReload = useCallback(async () => {
    const [profileResponse, customResponse, catalogResponse] =
      await Promise.all([
        EvaluationsService.readMetricProfiles({ limit: 200 }),
        EvaluationsService.readCustomMetrics({ limit: 200 }),
        EvaluationsService.readMetricCatalog(),
      ])
    setLocalProfiles(profileResponse.data)
    setLocalCustom(customResponse.data)
    setLocalCatalog(catalogResponse.data)
  }, [])
  const reload = suppliedReload ?? localReload

  useEffect(() => {
    if (!suppliedReload)
      void localReload().catch(() => setError("프로필을 불러오지 못했습니다."))
  }, [localReload, suppliedReload])

  useEffect(() => {
    setSelectedId(null)
    setDraft(emptyProfile(scope))
    setError("")
  }, [scope])

  const visibleProfiles = profiles.filter(
    (profile) => (profile.evaluation_scope ?? "single_turn") === scope,
  )
  const availableCatalog = catalog.filter(
    (item) => item.evaluation_mode === modeForScope(scope),
  )
  const availableCustom = customMetrics.filter(
    (metric) => metric.evaluation_scope === scope && metric.is_active,
  )
  const catalogByType = useMemo(
    () => new Map(catalog.map((item) => [item.metric_type, item])),
    [catalog],
  )
  const customById = useMemo(
    () => new Map(customMetrics.map((item) => [item.id, item])),
    [customMetrics],
  )
  const weightTotal = draft.metrics.reduce(
    (sum, metric) => sum + metric.weight_percent,
    0,
  )

  const selectProfile = (profile: EvaluationMetricProfilePublic) => {
    setSelectedId(profile.id)
    setDraft({
      name: profile.name,
      description: profile.description ?? "",
      is_active: profile.is_active ?? true,
      evaluation_scope: profile.evaluation_scope ?? "single_turn",
      version: profile.version,
      metrics: (profile.metrics ?? []).map((metric) => ({
        metric_type: metric.metric_type,
        custom_metric_id: metric.custom_metric_id,
        weight_percent: metric.weight_percent,
        config: metric.config,
        custom_instruction: metric.custom_instruction,
      })),
    })
    setError("")
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (weightTotal !== 100)
      return setError("지표 가중치 합계는 정확히 100%여야 합니다.")
    const identities = draft.metrics.map(metricIdentity)
    if (new Set(identities).size !== identities.length)
      return setError("같은 메트릭을 중복 선택할 수 없습니다.")
    try {
      setBusy(true)
      setError("")
      const body = {
        name: draft.name.trim(),
        description: draft.description.trim() || null,
        is_active: draft.is_active,
        evaluation_scope: scope,
        evaluation_mode: modeForScope(scope),
        metrics: draft.metrics,
      }
      const saved = selectedId
        ? await EvaluationsService.updateMetricProfile({
            profileId: selectedId,
            requestBody: { ...body, expected_version: draft.version },
          })
        : await EvaluationsService.createMetricProfile({ requestBody: body })
      await reload()
      selectProfile(saved)
    } catch (requestError) {
      setError(errorMessage(requestError, "평가 프로필을 저장하지 못했습니다."))
    } finally {
      setBusy(false)
    }
  }

  const removeProfile = async () => {
    if (!selectedId) return
    try {
      setBusy(true)
      setError("")
      await EvaluationsService.deleteMetricProfile({ profileId: selectedId })
      setSelectedId(null)
      setDraft(emptyProfile(scope))
      await reload()
    } catch (requestError) {
      setError(
        errorMessage(
          requestError,
          "데이터셋이나 실행에서 참조 중인 프로필은 삭제할 수 없습니다.",
        ),
      )
    } finally {
      setBusy(false)
    }
  }

  const addMetric = () => {
    const used = new Set(draft.metrics.map(metricIdentity))
    const builtin = availableCatalog.find(
      (item) => !used.has(`builtin:${item.metric_type}`),
    )
    const custom = availableCustom.find(
      (item) => !used.has(`custom:${item.id}`),
    )
    const next = builtin
      ? { metric_type: builtin.metric_type, weight_percent: 1 }
      : custom
        ? { custom_metric_id: custom.id, weight_percent: 1 }
        : null
    if (next)
      setDraft((current) => ({
        ...current,
        metrics: [...current.metrics, next],
      }))
  }

  const updateIdentity = (index: number, identity: string) => {
    setDraft((current) => ({
      ...current,
      metrics: current.metrics.map((metric, itemIndex) =>
        itemIndex !== index
          ? metric
          : identity.startsWith("custom:")
            ? {
                custom_metric_id: identity.slice(7),
                weight_percent: metric.weight_percent,
              }
            : {
                metric_type: identity.slice(8) as EvaluationMetricType,
                weight_percent: metric.weight_percent,
              },
      ),
    }))
  }

  return (
    <section className="console-surface overflow-hidden">
      <div className="flex items-start justify-between gap-3 border-b px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold">공유 메트릭 프로필</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            최종 점수 = Σ(메트릭 점수 × 가중치 / 100). 가중치 합계는 정확히
            100%여야 합니다.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            setSelectedId(null)
            setDraft(emptyProfile(scope))
            setError("")
          }}
        >
          <Plus /> 새 프로필
        </Button>
      </div>
      <div className="grid gap-5 p-5 xl:grid-cols-[280px_minmax(0,1fr)]">
        <div className="space-y-2">
          {visibleProfiles.map((profile) => (
            <button
              key={profile.id}
              type="button"
              className={`w-full rounded-md border p-3 text-left ${selectedId === profile.id ? "border-primary bg-primary/5" : "hover:bg-muted/50"}`}
              onClick={() => selectProfile(profile)}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="font-medium">{profile.name}</span>
                <Badge variant={profile.is_active ? "secondary" : "outline"}>
                  v{profile.version}
                </Badge>
              </span>
              <span className="mt-1 block text-xs text-muted-foreground">
                {profile.metrics?.length ?? 0}개 메트릭
              </span>
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
            실행 화면에서 선택 가능
          </label>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p
              role="status"
              aria-label="평가지표 가중치 합계"
              className={`text-sm ${weightTotal === 100 ? "text-emerald-700 dark:text-emerald-400" : "text-destructive"}`}
            >
              가중치 합계 {weightTotal}% ·{" "}
              {weightTotal === 100 ? "저장 가능" : "100%로 맞춰 주세요"}
            </p>
            <Button
              type="button"
              variant="outline"
              disabled={draft.metrics.length >= 16}
              onClick={addMetric}
            >
              <Plus /> 메트릭 추가
            </Button>
          </div>
          <div className="space-y-3">
            {draft.metrics.map((metric, index) => {
              const identity = metricIdentity(metric)
              const custom = metric.custom_metric_id
                ? customById.get(metric.custom_metric_id)
                : undefined
              const builtin = metric.metric_type
                ? catalogByType.get(metric.metric_type)
                : undefined
              const label = custom?.name ?? builtin?.display_name ?? identity
              return (
                <div
                  key={`${index}-${identity}`}
                  className="rounded-md border p-4"
                >
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_120px_auto]">
                    <label
                      htmlFor={`metric-${index}-type`}
                      className="space-y-1 text-xs"
                    >
                      <span>메트릭</span>
                      <select
                        id={`metric-${index}-type`}
                        aria-label={`지표 ${index + 1} 타입`}
                        className="h-9 w-full rounded-md border bg-background px-3"
                        value={identity}
                        onChange={(event) =>
                          updateIdentity(index, event.target.value)
                        }
                      >
                        {availableCatalog.map((item) => (
                          <option
                            key={item.metric_type}
                            value={`builtin:${item.metric_type}`}
                          >
                            {item.display_name}
                          </option>
                        ))}
                        {availableCustom.map((item) => (
                          <option key={item.id} value={`custom:${item.id}`}>
                            Custom · {item.name} v{item.version}
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
                        aria-label={`${label} 가중치`}
                        type="number"
                        min={1}
                        max={100}
                        value={metric.weight_percent}
                        onChange={(event) =>
                          setDraft((current) => ({
                            ...current,
                            metrics: current.metrics.map((item, itemIndex) =>
                              itemIndex === index
                                ? {
                                    ...item,
                                    weight_percent: Number(event.target.value),
                                  }
                                : item,
                            ),
                          }))
                        }
                      />
                    </label>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`${label} 지표 삭제`}
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
                  <p className="mt-2 text-xs text-muted-foreground">
                    {custom
                      ? `스냅샷 저장: CustomMetric v${custom.version} · ${custom.required_keys.join(", ")}`
                      : builtin?.description}
                  </p>
                  {(builtin?.required_config ?? []).map((configKey) => (
                    <label
                      key={configKey}
                      htmlFor={`metric-${index}-config-${configKey}`}
                      className="mt-2 block space-y-1 text-xs"
                    >
                      <span>필수 설정 · {configKey}</span>
                      <Input
                        id={`metric-${index}-config-${configKey}`}
                        value={String(metric.config?.[configKey] ?? "")}
                        onChange={(event) =>
                          setDraft((current) => ({
                            ...current,
                            metrics: current.metrics.map((item, itemIndex) =>
                              itemIndex === index
                                ? {
                                    ...item,
                                    config: {
                                      ...(item.config ?? {}),
                                      [configKey]: event.target.value,
                                    },
                                  }
                                : item,
                            ),
                          }))
                        }
                      />
                    </label>
                  ))}
                </div>
              )
            })}
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={busy || weightTotal !== 100}>
              <Save />{" "}
              {busy ? "저장 중…" : selectedId ? "새 버전 저장" : "프로필 저장"}
            </Button>
            {selectedId && (
              <Button
                type="button"
                variant="destructive"
                disabled={busy}
                onClick={() => void removeProfile()}
              >
                <Trash2 /> 프로필 삭제
              </Button>
            )}
          </div>
        </form>
      </div>
    </section>
  )
}

export function MetricManagement() {
  const [scope, setScope] = useState<EvaluationScope>("quick_upload")
  const [profiles, setProfiles] = useState<EvaluationMetricProfilePublic[]>([])
  const [customMetrics, setCustomMetrics] = useState<CustomMetricPublic[]>([])
  const [catalog, setCatalog] = useState<EvaluationMetricCatalogItem[]>([])
  const [contracts, setContracts] = useState<CustomMetricPlaceholderContract[]>(
    [],
  )
  const [contractError, setContractError] = useState("")
  const [error, setError] = useState("")
  const reload = useCallback(async () => {
    const [profileResponse, customResponse, catalogResponse] =
      await Promise.all([
        EvaluationsService.readMetricProfiles({ limit: 200 }),
        EvaluationsService.readCustomMetrics({ limit: 200 }),
        EvaluationsService.readMetricCatalog(),
      ])
    setProfiles(profileResponse.data)
    setCustomMetrics(customResponse.data)
    setCatalog(catalogResponse.data)
  }, [])
  const loadContracts = useCallback(async () => {
    try {
      const response =
        await EvaluationsService.readCustomMetricPlaceholderContracts()
      setContracts(response.data)
      setContractError("")
    } catch (requestError) {
      setContracts([])
      setContractError(
        errorMessage(
          requestError,
          "Backend placeholder 계약을 불러오지 못해 CustomMetric을 저장할 수 없습니다.",
        ),
      )
    }
  }, [])
  useEffect(() => {
    void reload().catch((requestError) =>
      setError(
        errorMessage(requestError, "메트릭 관리 데이터를 불러오지 못했습니다."),
      ),
    )
    void loadContracts()
  }, [loadContracts, reload])
  return (
    <div className="space-y-6">
      <div
        className="flex gap-2 overflow-x-auto"
        role="tablist"
        aria-label="평가 범위"
      >
        {scopes.map((item) => (
          <Button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={scope === item.value}
            variant={scope === item.value ? "default" : "outline"}
            onClick={() => setScope(item.value)}
          >
            {item.label}
          </Button>
        ))}
      </div>
      {error && (
        <p
          role="alert"
          className="whitespace-pre-line text-sm text-destructive"
        >
          {error}
        </p>
      )}
      <CustomMetricsPanel
        metrics={customMetrics}
        contracts={contracts}
        contractError={contractError}
        scope={scope}
        reload={reload}
      />
      <MetricProfilesPanel
        profiles={profiles}
        customMetrics={customMetrics}
        catalog={catalog}
        scope={scope}
        reload={reload}
      />
    </div>
  )
}
