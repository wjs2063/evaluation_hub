import { createFileRoute, Navigate } from "@tanstack/react-router"

export const Route = createFileRoute("/_layout/evaluation-multi-turn/")({
  component: MultiTurnIndex,
})

function MultiTurnIndex() {
  return <Navigate to="/evaluation-multi-turn/live-test" replace />
}
