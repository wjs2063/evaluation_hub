import { createFileRoute, Outlet } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/evaluation-single-turn")({
  component: SingleTurnEvaluation,
  head: () => ({ meta: [{ title: "Single-turn Evaluation - EvalHub" }] }),
})

function SingleTurnEvaluation() {
  return <Outlet />
}
