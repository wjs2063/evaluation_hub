import { cn } from "@/lib/utils"

interface ItemIndicatorProps {
  active?: boolean
  className?: string
}

export function ItemIndicator({
  active = false,
  className,
}: ItemIndicatorProps) {
  return (
    <span
      aria-hidden="true"
      data-sidebar="item-indicator"
      data-active={active}
      className={cn(
        "size-2 shrink-0 rounded-full",
        active ? "bg-cyan-400" : "bg-sidebar-foreground/25",
        className,
      )}
    />
  )
}
