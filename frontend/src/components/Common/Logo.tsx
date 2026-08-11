import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content = (
    <div
      className={cn(
        "flex items-center gap-2.5",
        variant === "responsive" && "group-data-[collapsible=icon]:gap-0",
        className,
      )}
    >
      <span className="grid size-7 shrink-0 place-items-center rounded-[5px] border border-sidebar-primary/50 bg-sidebar-primary/10 text-xs font-semibold text-sidebar-primary">
        E
      </span>
      <span className="min-w-0 truncate text-sm font-medium tracking-tight">
        EvaluationHub
      </span>
    </div>
  )

  if (!asLink) {
    return content
  }

  return (
    <Link
      to="/"
      aria-label="Go to overview"
      className="block rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
    >
      {content}
    </Link>
  )
}
