import axios from "axios"
import { Save, Trash2 } from "lucide-react"
import { type FormEvent, useCallback, useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

type Endpoint = {
  id: string
  name: string
  base_url: string
  is_active: boolean
  headers_configured: boolean
}

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? "" })
api.interceptors.request.use((config) => {
  config.headers.Authorization = `Bearer ${localStorage.getItem("access_token") ?? ""}`
  return config
})

export function EvaluationEndpoints() {
  const [items, setItems] = useState<Endpoint[]>([])
  const [name, setName] = useState("")
  const [baseUrl, setBaseUrl] = useState("")
  const [headers, setHeaders] = useState("{}")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    const { data } = await api.get<{ data: Endpoint[] }>(
      "/api/v1/evaluations/endpoints",
      { params: { limit: 200 } },
    )
    setItems(data.data)
  }, [])

  useEffect(() => {
    load().catch(() => setError("허용 서버 목록을 불러오지 못했습니다."))
  }, [load])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    try {
      setBusy(true)
      setError("")
      const parsed = JSON.parse(headers)
      await api.post("/api/v1/evaluations/endpoints", {
        name,
        base_url: baseUrl,
        headers: parsed,
      })
      setName("")
      setBaseUrl("")
      setHeaders("{}")
      await load()
    } catch (requestError) {
      setError(
        axios.isAxiosError(requestError)
          ? (requestError.response?.data?.detail ?? "서버 등록에 실패했습니다.")
          : "헤더는 JSON 객체여야 합니다.",
      )
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (item: Endpoint) => {
    if (
      !confirm(
        `${item.name} 서버를 ${item.is_active ? "비활성화" : "활성화"}할까요?`,
      )
    )
      return
    await api.put(`/api/v1/evaluations/endpoints/${item.id}`, {
      is_active: !item.is_active,
    })
    await load()
  }

  return (
    <section className="console-surface overflow-hidden">
      <div className="border-b px-5 py-4">
        <h2 className="text-sm font-semibold">허용된 A 서버</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          로컬 개발 환경에서는 HTTP/HTTPS, 그 외 환경에서는 HTTPS 서버만
          등록됩니다. 인증 헤더는 암호화되어 저장되며 이후 화면에 값을 다시
          표시하지 않습니다.
        </p>
      </div>
      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-2">
          {items.length === 0 && (
            <p className="rounded-md bg-muted p-3 text-sm text-muted-foreground">
              등록된 A 서버가 없습니다. 라이브 평가 전에 서버를 등록하세요.
            </p>
          )}
          {items.map((item) => (
            <div
              key={item.id}
              className="flex items-center justify-between gap-3 rounded-md border p-3"
            >
              <div className="min-w-0">
                <p className="font-medium">{item.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {item.base_url} · {item.is_active ? "active" : "inactive"}{" "}
                  {item.headers_configured && "· credentials configured"}
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`${item.name} ${item.is_active ? "비활성화" : "활성화"}`}
                onClick={() => toggle(item)}
              >
                <Trash2 />
              </Button>
            </div>
          ))}
        </div>
        <form className="space-y-3 rounded-md border p-4" onSubmit={submit}>
          <p className="text-sm font-medium">서버 등록</p>
          <Input
            value={name}
            placeholder="서버 이름"
            onChange={(event) => setName(event.target.value)}
          />
          <Input
            value={baseUrl}
            placeholder="https://api.example.com/v1/respond"
            onChange={(event) => setBaseUrl(event.target.value)}
          />
          <textarea
            aria-label="Encrypted request headers JSON"
            className="min-h-24 w-full rounded-md border bg-transparent p-2 font-mono text-xs"
            value={headers}
            onChange={(event) => setHeaders(event.target.value)}
          />
          {error && <p className="text-xs text-destructive">{error}</p>}
          <Button
            className="w-full"
            type="submit"
            disabled={busy || !name || !baseUrl}
          >
            <Save /> {busy ? "등록 중…" : "서버 등록"}
          </Button>
        </form>
      </div>
    </section>
  )
}
