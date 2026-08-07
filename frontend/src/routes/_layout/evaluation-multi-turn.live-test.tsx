import { createFileRoute } from "@tanstack/react-router"

import { MultiTurnWorkspace } from "@/components/Evaluations/MultiTurnWorkspace"

export const Route = createFileRoute(
  "/_layout/evaluation-multi-turn/live-test",
)({
  component: MultiTurnLiveTest,
  head: () => ({ meta: [{ title: "Multi-turn Live API Test - EvalHub" }] }),
})

function MultiTurnLiveTest() {
  return <MultiTurnWorkspace />
}
