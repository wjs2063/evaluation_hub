import { createFileRoute, Outlet } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/evaluation-multi-turn")({
  component: MultiTurnEvaluation,
  head: () => ({ meta: [{ title: "Multi-turn Evaluation - EvalHub" }] }),
})

function MultiTurnEvaluation() {
  return <Outlet />
}
