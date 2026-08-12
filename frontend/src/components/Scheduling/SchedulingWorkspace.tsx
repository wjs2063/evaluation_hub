import axios from "axios"
import {
  CalendarClock,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Plus,
  Save,
  Trash2,
} from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { PageHeader } from "@/components/Common/PageHeader"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import useAuth from "@/hooks/useAuth"

type Target = {
  id: string
  name: string
  description: string | null
}
type ScheduleType = "interval" | "cron"
type TargetType = "single_turn" | "multi_turn"
type Schedule = {
  id: string
  owner_id: string
  owner_name: string | null
  name: string
  schedule_type: ScheduleType
  target_type: TargetType
  target_id: string
  target_name: string
  target_description: string | null
  interval_seconds: number | null
  cron_expression: string | null
  timezone: string
  is_active: boolean
  next_run_at: string
  last_enqueued_at: string | null
}

const PAGE_SIZE = 20
const api = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? "" })
api.interceptors.request.use((config) => {
  config.headers.Authorization = `Bearer ${localStorage.getItem("access_token") ?? ""}`
  return config
})

const localDateTime = (value: string) => {
  const date = new Date(value)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16)
}

const firstRun = () => {
  const date = new Date(Date.now() + 5 * 60_000)
  date.setSeconds(0, 0)
  return localDateTime(date.toISOString())
}

const requestError = (error: unknown, fallback: string) =>
  axios.isAxiosError(error) && typeof error.response?.data?.detail === "string"
    ? error.response.data.detail
    : fallback

export function SchedulingWorkspace() {
  const { user } = useAuth()
  const [datasets, setDatasets] = useState<Target[]>([])
  const [scenarios, setScenarios] = useState<Target[]>([])
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [count, setCount] = useState(0)
  const [page, setPage] = useState(0)
  const [name, setName] = useState("정기 품질 평가")
  const [targetType, setTargetType] = useState<TargetType>("single_turn")
  const [targetId, setTargetId] = useState("")
  const [scheduleType, setScheduleType] = useState<ScheduleType>("interval")
  const [intervalMinutes, setIntervalMinutes] = useState(60)
  const [cronExpression, setCronExpression] = useState("0 9 * * 1-5")
  const [timezone, setTimezone] = useState("Asia/Seoul")
  const [nextRunAt, setNextRunAt] = useState(firstRun)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const targets = targetType === "single_turn" ? datasets : scenarios

  const loadSchedules = useCallback(async (requestedPage: number) => {
    const { data } = await api.get<{ data: Schedule[]; count: number }>(
      "/api/v1/evaluations/schedules",
      { params: { offset: requestedPage * PAGE_SIZE, limit: PAGE_SIZE } },
    )
    setSchedules(data.data)
    setCount(data.count)
  }, [])

  useEffect(() => {
    Promise.all([
      api.get<{ data: Target[] }>("/api/v1/evaluations/single-turn/datasets", {
        params: { limit: 200 },
      }),
      api.get<{ data: Target[] }>("/api/v1/evaluations/multi-turn/datasets", {
        params: { limit: 200 },
      }),
      loadSchedules(0),
    ])
      .then(([datasetResult, scenarioResult]) => {
        setDatasets(datasetResult.data.data)
        setScenarios(scenarioResult.data.data)
        setTargetId(datasetResult.data.data[0]?.id ?? "")
      })
      .catch((loadError) =>
        setError(
          requestError(loadError, "스케줄 등록현황을 불러오지 못했습니다."),
        ),
      )
  }, [loadSchedules])

  useEffect(() => {
    loadSchedules(page).catch((loadError) =>
      setError(
        requestError(loadError, "스케줄 등록현황을 불러오지 못했습니다."),
      ),
    )
  }, [loadSchedules, page])

  const changeTargetType = (value: TargetType) => {
    setTargetType(value)
    const nextTargets = value === "single_turn" ? datasets : scenarios
    setTargetId(nextTargets[0]?.id ?? "")
  }

  const createSchedule = async () => {
    if (!name.trim() || !targetId) {
      setError("스케줄 이름과 실행 대상을 선택해 주세요.")
      return
    }
    try {
      setBusy(true)
      setError("")
      await api.post("/api/v1/evaluations/schedules", {
        name: name.trim(),
        target_type: targetType,
        target_id: targetId,
        schedule_type: scheduleType,
        interval_seconds:
          scheduleType === "interval"
            ? Math.max(1, intervalMinutes) * 60
            : null,
        cron_expression: scheduleType === "cron" ? cronExpression.trim() : null,
        timezone,
        next_run_at:
          scheduleType === "interval"
            ? new Date(nextRunAt).toISOString()
            : null,
        is_active: true,
      })
      setPage(0)
      await loadSchedules(0)
    } catch (createError) {
      setError(requestError(createError, "스케줄을 등록하지 못했습니다."))
    } finally {
      setBusy(false)
    }
  }

  const patchSchedule = (id: string, patch: Partial<Schedule>) => {
    setSchedules((current) =>
      current.map((schedule) =>
        schedule.id === id ? { ...schedule, ...patch } : schedule,
      ),
    )
  }

  const saveSchedule = async (schedule: Schedule) => {
    try {
      setBusy(true)
      setError("")
      await api.put(`/api/v1/evaluations/schedules/${schedule.id}`, {
        name: schedule.name,
        schedule_type: schedule.schedule_type,
        interval_seconds: schedule.interval_seconds,
        cron_expression: schedule.cron_expression,
        timezone: schedule.timezone,
        is_active: schedule.is_active,
        next_run_at:
          schedule.schedule_type === "interval" ? schedule.next_run_at : null,
      })
      await loadSchedules(page)
    } catch (saveError) {
      setError(requestError(saveError, "스케줄을 수정하지 못했습니다."))
    } finally {
      setBusy(false)
    }
  }

  const deleteSchedule = async (schedule: Schedule) => {
    if (!confirm(`'${schedule.name}' 스케줄을 삭제할까요?`)) return
    try {
      await api.delete(`/api/v1/evaluations/schedules/${schedule.id}`)
      const nextPage = schedules.length === 1 && page > 0 ? page - 1 : page
      setPage(nextPage)
      await loadSchedules(nextPage)
    } catch (deleteError) {
      setError(requestError(deleteError, "스케줄을 삭제하지 못했습니다."))
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Automation"
        title="스케줄링"
        description="싱글턴 데이터셋과 멀티턴 시나리오를 주기 또는 Cron으로 자동 실행합니다."
      />
      {error && (
        <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </p>
      )}
      <section className="console-surface p-5">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <CalendarClock className="size-4 text-primary" />
            <div>
              <h2 className="text-sm font-semibold">스케줄 등록</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                주기 실행은 최초 실행 시각부터 반복하고, Cron은 선택한 시간대의
                5필드 표현식을 사용합니다.
              </p>
            </div>
          </div>
          <Dialog>
            <DialogTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label="Cron 사용법 보기"
                className="shrink-0"
              >
                <CircleHelp /> Cron 도움말
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Cron 표현식 사용법</DialogTitle>
                <DialogDescription>
                  선택한 시간대를 기준으로 분·시·일·월·요일의 5개 필드를
                  입력합니다.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 text-sm">
                <div className="overflow-x-auto rounded-md border bg-muted/30 p-3">
                  <code className="whitespace-nowrap font-mono">
                    분 시 일 월 요일
                  </code>
                  <p className="mt-2 text-xs text-muted-foreground">
                    순서: minute (0–59), hour (0–23), day (1–31), month (1–12),
                    weekday (0–7, 일요일은 0 또는 7)
                  </p>
                </div>
                <p className="text-xs text-muted-foreground">
                  <code>*</code> 전체, <code>,</code> 목록, <code>-</code> 범위,
                  <code>/</code> 간격을 사용할 수 있습니다.
                </p>
                <div className="grid gap-2">
                  {[
                    ["*/10 * * * *", "10분마다"],
                    ["0 * * * *", "매시 정각"],
                    ["0 9 * * 1-5", "평일 오전 9시"],
                    ["30 18 1 * *", "매월 1일 오후 6시 30분"],
                    ["0 0 * * 0", "매주 일요일 자정"],
                  ].map(([expression, description]) => (
                    <div
                      key={expression}
                      className="grid grid-cols-[minmax(130px,auto)_1fr] gap-3 rounded-md border px-3 py-2"
                    >
                      <code className="font-mono">{expression}</code>
                      <span className="text-muted-foreground">
                        {description}
                      </span>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  예시는 기본 시간대인 <code>Asia/Seoul</code> 기준입니다.
                  시간대 필드에는 IANA 이름을 입력하세요.
                </p>
              </div>
            </DialogContent>
          </Dialog>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label htmlFor="schedule-name" className="space-y-1 text-xs">
            <span>스케줄 이름</span>
            <Input
              id="schedule-name"
              aria-label="Schedule name"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="space-y-1 text-xs">
            <span>테스트 유형</span>
            <select
              aria-label="Schedule target type"
              className="h-9 w-full rounded-md border bg-transparent px-3"
              value={targetType}
              onChange={(event) =>
                changeTargetType(event.target.value as TargetType)
              }
            >
              <option value="single_turn">Single Turn</option>
              <option value="multi_turn">Multi Turn</option>
            </select>
          </label>
          <label className="space-y-1 text-xs">
            <span>실행 대상</span>
            <select
              aria-label="Schedule target"
              className="h-9 w-full rounded-md border bg-transparent px-3"
              value={targetId}
              onChange={(event) => setTargetId(event.target.value)}
            >
              <option value="">대상을 선택하세요</option>
              {targets.map((target) => (
                <option key={target.id} value={target.id}>
                  {target.name}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-xs">
            <span>실행 방식</span>
            <select
              aria-label="Schedule type"
              className="h-9 w-full rounded-md border bg-transparent px-3"
              value={scheduleType}
              onChange={(event) =>
                setScheduleType(event.target.value as ScheduleType)
              }
            >
              <option value="interval">주기 실행</option>
              <option value="cron">Cron</option>
            </select>
          </label>
          {scheduleType === "interval" ? (
            <>
              <label htmlFor="schedule-interval" className="space-y-1 text-xs">
                <span>실행 간격(분)</span>
                <Input
                  id="schedule-interval"
                  aria-label="Schedule interval minutes"
                  type="number"
                  min={1}
                  value={intervalMinutes}
                  onChange={(event) =>
                    setIntervalMinutes(Number(event.target.value))
                  }
                />
              </label>
              <label htmlFor="schedule-first-run" className="space-y-1 text-xs">
                <span>최초 실행</span>
                <Input
                  id="schedule-first-run"
                  aria-label="Schedule first run"
                  type="datetime-local"
                  value={nextRunAt}
                  onChange={(event) => setNextRunAt(event.target.value)}
                />
              </label>
            </>
          ) : (
            <label
              htmlFor="cron-expression"
              className="space-y-1 text-xs md:col-span-2"
            >
              <span>Cron 표현식</span>
              <Input
                id="cron-expression"
                aria-label="Cron expression"
                className="font-mono"
                value={cronExpression}
                onChange={(event) => setCronExpression(event.target.value)}
              />
              <span className="text-muted-foreground">
                예: 평일 오전 9시 `0 9 * * 1-5`
              </span>
            </label>
          )}
          <label htmlFor="schedule-timezone" className="space-y-1 text-xs">
            <span>시간대</span>
            <Input
              id="schedule-timezone"
              aria-label="Schedule timezone"
              value={timezone}
              onChange={(event) => setTimezone(event.target.value)}
            />
          </label>
          <div className="flex items-end">
            <Button
              className="w-full"
              disabled={busy || !targetId}
              onClick={createSchedule}
            >
              <Plus /> 등록
            </Button>
          </div>
        </div>
      </section>

      <section className="console-surface overflow-hidden">
        <div className="border-b p-5">
          <h2 className="text-sm font-semibold">등록현황</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {user?.is_superuser
              ? "관리자는 모든 사용자의 스케줄을 관리할 수 있습니다."
              : "본인이 등록한 스케줄만 조회·수정·삭제할 수 있습니다."}
          </p>
        </div>
        {schedules.length === 0 ? (
          <p className="p-8 text-center text-sm text-muted-foreground">
            등록된 스케줄이 없습니다.
          </p>
        ) : (
          <div className="divide-y">
            {schedules.map((schedule) => (
              <article
                key={schedule.id}
                className="grid gap-3 p-4 lg:grid-cols-[minmax(180px,1fr)_minmax(160px,1fr)_minmax(240px,1.4fr)_auto] lg:items-center"
              >
                <div className="min-w-0">
                  <Input
                    aria-label={`Schedule name ${schedule.id}`}
                    value={schedule.name}
                    onChange={(event) =>
                      patchSchedule(schedule.id, { name: event.target.value })
                    }
                  />
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {schedule.owner_name ?? "-"} ·{" "}
                    {schedule.target_type === "single_turn"
                      ? "Single Turn"
                      : "Multi Turn"}
                  </p>
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {schedule.target_name}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {schedule.target_description || "설명 없음"}
                  </p>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <select
                    aria-label={`Schedule mode ${schedule.id}`}
                    className="h-9 rounded-md border bg-transparent px-3 text-sm"
                    value={schedule.schedule_type}
                    onChange={(event) =>
                      patchSchedule(schedule.id, {
                        schedule_type: event.target.value as ScheduleType,
                        interval_seconds:
                          event.target.value === "interval" ? 3600 : null,
                        cron_expression:
                          event.target.value === "cron" ? "0 9 * * 1-5" : null,
                      })
                    }
                  >
                    <option value="interval">주기 실행</option>
                    <option value="cron">Cron</option>
                  </select>
                  {schedule.schedule_type === "interval" ? (
                    <Input
                      aria-label={`Schedule interval ${schedule.id}`}
                      type="number"
                      min={1}
                      value={(schedule.interval_seconds ?? 60) / 60}
                      onChange={(event) =>
                        patchSchedule(schedule.id, {
                          interval_seconds:
                            Math.max(1, Number(event.target.value)) * 60,
                        })
                      }
                    />
                  ) : (
                    <Input
                      aria-label={`Cron expression ${schedule.id}`}
                      className="font-mono"
                      value={schedule.cron_expression ?? ""}
                      onChange={(event) =>
                        patchSchedule(schedule.id, {
                          cron_expression: event.target.value,
                        })
                      }
                    />
                  )}
                  <Input
                    aria-label={`Schedule timezone ${schedule.id}`}
                    value={schedule.timezone}
                    onChange={(event) =>
                      patchSchedule(schedule.id, {
                        timezone: event.target.value,
                      })
                    }
                  />
                  <label className="flex h-9 items-center gap-2 rounded-md border px-3 text-sm">
                    <input
                      aria-label={`Schedule active ${schedule.id}`}
                      type="checkbox"
                      checked={schedule.is_active}
                      onChange={(event) =>
                        patchSchedule(schedule.id, {
                          is_active: event.target.checked,
                        })
                      }
                    />
                    {schedule.is_active ? "활성" : "중지"}
                  </label>
                  <p className="text-xs text-muted-foreground sm:col-span-2">
                    다음 {new Date(schedule.next_run_at).toLocaleString()} ·
                    최근{" "}
                    {schedule.last_enqueued_at
                      ? new Date(schedule.last_enqueued_at).toLocaleString()
                      : "없음"}
                  </p>
                </div>
                <div className="flex justify-end gap-1">
                  <Button
                    variant="outline"
                    size="icon"
                    aria-label={`Save schedule ${schedule.name}`}
                    disabled={busy}
                    onClick={() => saveSchedule(schedule)}
                  >
                    <Save />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Delete schedule ${schedule.name}`}
                    onClick={() => deleteSchedule(schedule)}
                  >
                    <Trash2 />
                  </Button>
                </div>
              </article>
            ))}
          </div>
        )}
        <div className="flex items-center justify-between gap-3 border-t p-4 text-xs text-muted-foreground">
          <span>
            총 {count.toLocaleString()}건 · {count ? page + 1 : 0}/
            {Math.max(1, Math.ceil(count / PAGE_SIZE))} 페이지
          </span>
          <div className="flex gap-1">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 0}
              onClick={() => setPage((value) => Math.max(0, value - 1))}
            >
              <ChevronLeft /> 이전
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={(page + 1) * PAGE_SIZE >= count}
              onClick={() => setPage((value) => value + 1)}
            >
              다음 <ChevronRight />
            </Button>
          </div>
        </div>
      </section>
    </div>
  )
}
