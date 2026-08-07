import { createFileRoute } from "@tanstack/react-router"

import { MultiTurnRegressionWorkspace } from "@/components/Evaluations/MultiTurnRegressionWorkspace"

export const Route = createFileRoute(
  "/_layout/evaluation-multi-turn/regression",
)({
  component: MultiTurnRegression,
  head: () => ({
    meta: [{ title: "Multi-turn Regression Evaluation - EvalHub" }],
  }),
})

function MultiTurnRegression() {
  return <MultiTurnRegressionWorkspace />
}
