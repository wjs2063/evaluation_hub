import { Link } from "@tanstack/react-router"

import { ItemIndicator } from "@/components/Sidebar/ItemIndicator"
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
      <ItemIndicator active />
      <span className="min-w-0 leading-none">
        <span className="block text-[15px] font-semibold tracking-tight">
          EvaluationHub
        </span>
        <span className="mt-1 block text-[9px] font-medium uppercase tracking-[0.18em] opacity-50">
          AI Evaluation
        </span>
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
      className="block rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
    >
      {content}
    </Link>
  )
}
