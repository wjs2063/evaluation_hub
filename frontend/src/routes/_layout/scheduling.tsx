import { createFileRoute } from "@tanstack/react-router"

import { SchedulingWorkspace } from "@/components/Scheduling/SchedulingWorkspace"

export const Route = createFileRoute("/_layout/scheduling")({
  component: SchedulingPage,
  head: () => ({ meta: [{ title: "Scheduling - EvalHub" }] }),
})

function SchedulingPage() {
  return <SchedulingWorkspace />
}
