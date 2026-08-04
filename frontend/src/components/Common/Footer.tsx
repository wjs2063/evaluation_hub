export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="border-t px-6 py-3">
      <div className="flex items-center justify-between gap-4">
        <p className="text-xs text-muted-foreground">
          EvalHub AI Evaluation · {currentYear}
        </p>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <span className="size-1.5 rounded-full bg-emerald-500" />
          Operational
        </div>
      </div>
    </footer>
  )
}
