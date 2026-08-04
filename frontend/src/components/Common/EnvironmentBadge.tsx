import { appEnvironment, environmentLabels } from "@/config/environment"

const environmentStyles = {
  development: {
    container: "border-sky-500/25 bg-sky-500/5 text-sky-700 dark:text-sky-300",
    dot: "bg-sky-500",
  },
  staging: {
    container:
      "border-amber-500/25 bg-amber-500/5 text-amber-700 dark:text-amber-300",
    dot: "bg-amber-500",
  },
  production: {
    container:
      "border-emerald-500/25 bg-emerald-500/5 text-emerald-700 dark:text-emerald-300",
    dot: "bg-emerald-500",
  },
} as const

export function EnvironmentBadge() {
  const label = environmentLabels[appEnvironment]
  const styles = environmentStyles[appEnvironment]

  return (
    <div
      role="status"
      aria-label={`Environment: ${label}`}
      className={`flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs font-medium ${styles.container}`}
    >
      <span className={`size-1.5 rounded-full ${styles.dot}`} />
      <span className="hidden sm:inline">{label}</span>
    </div>
  )
}
