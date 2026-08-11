import type { ReactNode } from "react"

interface PageHeaderProps {
  eyebrow?: string
  title: string
  description: string
  action?: ReactNode
}

export function PageHeader({
  eyebrow = "Operations",
  title,
  description,
  action,
}: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-4 border-b pb-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <p className="console-label mb-1.5">{eyebrow}</p>
        <h1 className="truncate text-xl font-semibold tracking-tight sm:text-2xl">
          {title}
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          {description}
        </p>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}
