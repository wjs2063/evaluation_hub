import { Link } from "@tanstack/react-router"
import { Orbit } from "lucide-react"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const showText = variant !== "icon"
  const content = (
    <div
      className={cn(
        "flex items-center gap-2.5",
        variant === "responsive" && "group-data-[collapsible=icon]:gap-0",
        className,
      )}
    >
      <span className="relative grid size-8 shrink-0 place-items-center rounded-md bg-cyan-400 text-slate-950 shadow-[0_0_22px_rgb(34_211_238/0.22)]">
        <Orbit className="size-5" strokeWidth={2.2} />
        <span className="absolute -right-0.5 -top-0.5 size-2 rounded-full border-2 border-sidebar bg-orange-400" />
      </span>
      {showText && (
        <span
          className={cn(
            "min-w-0 leading-none",
            variant === "responsive" && "group-data-[collapsible=icon]:hidden",
          )}
        >
          <span className="block text-[15px] font-semibold tracking-tight">
            EvalHub
          </span>
          <span className="mt-1 block text-[9px] font-medium uppercase tracking-[0.18em] opacity-50">
            AI Evaluation
          </span>
        </span>
      )}
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
