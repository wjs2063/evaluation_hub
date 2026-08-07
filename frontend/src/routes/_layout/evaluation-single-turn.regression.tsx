import { createFileRoute } from "@tanstack/react-router"

import { RegressionWorkspace } from "@/components/Evaluations/RegressionWorkspace"

export const Route = createFileRoute(
  "/_layout/evaluation-single-turn/regression",
)({
  component: SingleTurnRegression,
  head: () => ({ meta: [{ title: "Regression Evaluation - EvalHub" }] }),
})

function SingleTurnRegression() {
  return <RegressionWorkspace />
}
